from __future__ import annotations

import argparse
import copy
import json
import os
import ipaddress
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import yaml

from . import __version__
from .config import (
    ConfigError,
    IntakeAdaSettings,
    data_dir,
    load,
    load_env_file,
    load_intake_config,
    mask_secrets,
    resolve_env,
    resolve_secret,
    validate_intake_config,
)
from .credentials import cloudflare_api_token, credential_environment, credential_status
from .core.jobs import register_builtin
from .core.memory import Memory
from .core.reflect import effective_persona
from .core.scheduler import Scheduler
from .core.growth_contracts import growth_timezone
from .application.growth_workflow import ensure_default_goal
from .application.designs import DEEPSEEK_DESIGN_MODEL, DesignServiceError
from .application.design_lab import DesignLabError, DesignLabService
from .hands.builder import BuilderError, OperationRoutingBuilder
from .hands.crawlseo import CrawlSEOError
from .hands.design_experiment import DesignExperimentError
from .hands.site_build import SiteOutputArtifactStore
from .runtime import Runtime
from .site_scaffold import initialize_payload_site


class AdminProcessLock:
    """Exclusive per-instance lock for the long-lived admin process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is None:
            return
        import fcntl

        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None


def _cmd_check(args: argparse.Namespace) -> int:
    config, sources = load(args.config)
    print(f"site-agent {__version__}")
    print("config sources:")
    for source in sources:
        print(f"  - {source}")
    resolved_env = credential_environment(config)
    env_state = resolve_env(config, resolved_env)
    credentials_state = credential_status(config, resolved_env)
    profile_backed = {
        "github_token": bool(credentials_state.get("github", {}).get("api_token_configured")),
        "cloudflare_api_token": bool(credentials_state.get("cloudflare", {}).get("api_token_configured")),
    }
    missing = [
        name
        for name, info in env_state.items()
        if not info["set"] and not profile_backed.get(name, False)
    ]
    print(f"env: set={[n for n in env_state if env_state[n]['set']]} missing={missing}")
    print(yaml.safe_dump({"credentials": credentials_state}, sort_keys=False).rstrip())
    print(yaml.safe_dump(mask_secrets(config), sort_keys=False))
    return 0


def _cmd_provision_seo(args: argparse.Namespace) -> int:
    """Provision GA4, Search Console, and a CrawlSEO project for one tenant."""
    from .application.seo_provisioning import SeoProvisioningError, SeoProvisioningService, write_token_env

    config, _sources = load(args.config)
    service = SeoProvisioningService(config)
    if not service.platform_available:
        print("[site-agent] platform Google/CrawlSEO wiring is not configured in this host profile", file=sys.stderr)
        return 1
    if args.verify_only:
        identifier = args.site_url or f"https://{args.domain}/"
        try:
            receipt = service.verify_gsc(
                identifier=identifier,
                property_url=args.gsc_property or identifier,
            )
        except (SeoProvisioningError, ValueError) as exc:
            print(f"[site-agent] Search Console verification failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(receipt, indent=2, ensure_ascii=False, default=str))
        return 0
    try:
        receipt = service.provision(
            tenant_id=args.tenant,
            domain=args.domain,
            project_name=args.project_name or args.tenant,
            organization_id=args.organization or "helloada",
            site_url=args.site_url or "",
            gsc_property=args.gsc_property or "",
            ga4_property_id=args.ga4_property_id or "",
            time_zone=args.time_zone,
            currency_code=args.currency,
            verify_gsc=not args.no_verify_gsc,
            verification_method=args.verification_method,
            domain_verification_method=args.domain_verification_method,
            ensure_host_resolves=args.ensure_host,
            idempotency_key=args.idempotency_key or "",
        )
    except (SeoProvisioningError, ValueError) as exc:
        print(f"[site-agent] SEO provisioning failed: {exc}", file=sys.stderr)
        return 1
    token = receipt.pop("credential_token", "")
    if token:
        directory = Path(args.persist_token_dir).expanduser() if args.persist_token_dir else (
            Path(args.config).expanduser().resolve().parent if args.config else Path.cwd()
        )
        path = write_token_env(directory, receipt["token_env"], token)
        receipt["token_file"] = str(path)
    else:
        receipt["token_file"] = ""
    print(json.dumps(receipt, indent=2, ensure_ascii=False, default=str))
    return 0


def _cmd_provision_email(args: argparse.Namespace) -> int:
    """Plan or apply email provisioning for one canonical registered tenant."""
    import datetime
    import secrets
    import tempfile

    from .application.email_bootstrap import auto_provision_email, prepare_email_plan
    from .application.email_provisioning import EmailProvisioningError
    from .application.seo_bootstrap import load_tenant_environment
    from .application.tenant_registration import load_provisioned_tenants
    from .config import deep_merge
    from .credentials import credential_environment

    host_config, _sources = load(args.config)
    host_env = credential_environment(host_config, os.environ)
    declared, tenant_env = load_provisioned_tenants(host_config, host_env)
    tenant_id = str(args.tenant or "").strip().lower()
    spec = declared.get(tenant_id)
    if not isinstance(spec, dict):
        raise ConfigError(f"tenant {tenant_id!r} is not present in the canonical provisioned tenant registry")

    config_path = Path(str(spec.get("config_path") or "")).expanduser().resolve()
    raw_tenant = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_tenant, dict):
        raise ConfigError("registered tenant configuration must be a mapping")
    config, _ = load(config_path, {**host_env, **tenant_env}, validate_integrations=False)
    section = host_config.get("workspace_api") if isinstance(host_config.get("workspace_api"), dict) else {}
    root_credentials = host_config.get("credentials") if isinstance(host_config.get("credentials"), dict) else {}
    section_credentials = section.get("credentials") if isinstance(section.get("credentials"), dict) else {}
    tenant_credentials = raw_tenant.get("credentials") if isinstance(raw_tenant.get("credentials"), dict) else {}
    config["credentials"] = deep_merge(deep_merge(root_credentials, section_credentials), tenant_credentials)
    config["observability"] = deep_merge(
        host_config.get("observability") if isinstance(host_config.get("observability"), dict) else {},
        raw_tenant.get("observability") if isinstance(raw_tenant.get("observability"), dict) else {},
    )
    config["source_deployment"] = deep_merge(
        config.get("source_deployment") if isinstance(config.get("source_deployment"), dict) else {},
        host_config.get("source_deployment") if isinstance(host_config.get("source_deployment"), dict) else {},
    )
    config["instance_name"] = tenant_id
    resolved_env = load_tenant_environment(config, {**host_env, **tenant_env})

    policy_overrides: dict[str, object] = {}
    if args.approve_mailgun_cutover:
        policy_overrides.update({
            "approvedLegacyMx": ["mxa.mailgun.org", "mxb.mailgun.org"],
            "approvedLegacySpf": "v=spf1 include:mailgun.org ~all",
            "allowLegacyMailgunCutover": True,
        })
    if args.allow_forwarding_cutover:
        policy_overrides["allowForwardingCutover"] = True
    email_domain_override = str(getattr(args, "email_domain", "") or "").strip()
    local_part_override = str(getattr(args, "local_part", "") or "").strip()
    if email_domain_override:
        policy_overrides["emailDomain"] = email_domain_override
    if local_part_override:
        policy_overrides["localPart"] = local_part_override

    try:
        plan, _policy, _ = prepare_email_plan(
            config,
            tenant_id=tenant_id,
            env=resolved_env,
            policy_overrides=policy_overrides,
        )
    except EmailProvisioningError as exc:
        print(f"[site-agent] Email preflight stopped without changes: {exc}", file=sys.stderr)
        return 1

    summary = {
        "state": "ready_to_apply",
        "tenant": tenant_id,
        "domain": plan["domain"],
        "address": plan["address"],
        "worker": plan["worker"],
        "preflightSha256": plan["snapshotSha256"],
        "operations": plan["operations"],
        "mode": "apply" if args.apply else "plan_only",
    }
    if not args.apply:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print("Read-only preflight only; pass --apply to configure the registered tenant and Cloudflare.")
        return 0

    if isinstance(config.get("messages"), dict) and config["messages"].get("enabled") is False:
        raise ConfigError("messages.enabled is false for this tenant; enable the Messages capability before provisioning email")

    now = datetime.datetime.now(datetime.timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4)
    data_dir = Path(str(config.get("data_dir") or "")).expanduser().resolve()
    if data_dir == Path(data_dir.anchor) or not str(config.get("data_dir") or "").strip():
        raise ConfigError("registered tenant has no dedicated data_dir for a protected provisioning receipt")
    receipt_root = data_dir / "email-provisioning"
    receipt_runs = receipt_root / "runs"
    receipt_dir = receipt_runs / run_id
    receipt_path = receipt_dir / "receipt.json"

    def write_receipt(value: dict[str, object]) -> None:
        for directory in (receipt_root, receipt_runs, receipt_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                directory.chmod(0o700)
            except OSError:
                pass
        fd, temporary_name = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=receipt_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, receipt_path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    # Record the exact read-only preflight before any config or provider write.
    receipt: dict[str, object] = {
        "schema": 1,
        **summary,
        "state": "preflight_complete",
        "runId": run_id,
        "approvedMailgunCutover": bool(args.approve_mailgun_cutover),
        "approvedForwardingCutover": bool(args.allow_forwarding_cutover),
        "startedAt": now.isoformat(timespec="seconds"),
        # May include a personal forwarding destination; this exact before
        # state is stored only in this mode-0600 tenant receipt, never stdout.
        "preflightSnapshot": plan["snapshot"],
    }
    write_receipt(receipt)

    messages = raw_tenant.get("messages") if isinstance(raw_tenant.get("messages"), dict) else {}
    messages = dict(messages)
    email = messages.get("email") if isinstance(messages.get("email"), dict) else {}
    email = dict(email)
    email["enabled"] = True
    email.setdefault("local_part", "hello")
    if email_domain_override:
        email["domain"] = email_domain_override.lower().rstrip(".")
    if local_part_override:
        email["local_part"] = local_part_override.lower()
    provisioning = email.get("provisioning") if isinstance(email.get("provisioning"), dict) else {}
    email["provisioning"] = {**dict(provisioning), "auto": True}
    messages["email"] = email
    raw_tenant["messages"] = messages
    from .application.tenant_registration import TenantRegistrationService

    TenantRegistrationService._replace_config(config_path, raw_tenant)
    config, _ = load(config_path, {**host_env, **tenant_env}, validate_integrations=False)
    config["credentials"] = deep_merge(deep_merge(root_credentials, section_credentials), tenant_credentials)
    config["observability"] = deep_merge(
        host_config.get("observability") if isinstance(host_config.get("observability"), dict) else {},
        raw_tenant.get("observability") if isinstance(raw_tenant.get("observability"), dict) else {},
    )
    config["source_deployment"] = deep_merge(
        config.get("source_deployment") if isinstance(config.get("source_deployment"), dict) else {},
        host_config.get("source_deployment") if isinstance(host_config.get("source_deployment"), dict) else {},
    )
    config["instance_name"] = tenant_id
    resolved_env = load_tenant_environment(config, {**host_env, **tenant_env})
    receipt["state"] = "applying"
    write_receipt(receipt)

    memory = Memory(data_dir / "memory.db")
    try:
        state, _resolved = auto_provision_email(
            config,
            tenant_id=tenant_id,
            memory=memory,
            env=resolved_env,
            policy_overrides=policy_overrides,
            expected_snapshot_sha256=str(plan["snapshotSha256"]),
        )
    finally:
        memory.close()
    receipt.update(state)
    receipt["runId"] = run_id
    receipt["receiptPath"] = str(receipt_path)
    write_receipt(receipt)
    print(json.dumps({
        key: receipt.get(key)
        for key in (
            "state", "tenant", "domain", "address", "worker", "runId",
            "preflightSha256", "operations", "error", "completedAt", "receiptPath",
        )
        if key in receipt
    }, indent=2, ensure_ascii=False, default=str))
    return 0 if receipt.get("state") == "active" else 1


def _cmd_init_site(args: argparse.Namespace) -> int:
    root = initialize_payload_site(args.directory, args.name, args.url)
    print(f"initialized canonical Payload site: {root}")
    print("created: Next.js/React/Payload customer template with the HelloAda admin package")
    return 0


def _cmd_provision_r2(args: argparse.Namespace) -> int:
    from .hands.cloudflare_r2 import CloudflareR2Provisioner, R2ProvisioningError, write_instance_r2_config

    config_path = Path(args.config or "config.yaml")
    config, _ = load(config_path)
    bootstrap_env_path = Path(args.bootstrap_env_file or ".env")
    bootstrap_env = credential_environment(config, load_env_file(bootstrap_env_path, dict(os.environ)))
    token = cloudflare_api_token(config, bootstrap_env) or resolve_secret(config, "cloudflare_api_token", bootstrap_env)
    if not token:
        raise ConfigError("Cloudflare API token is not set for R2 provisioning")
    bucket = args.bucket or f"helloada-{args.instance}-media"
    provisioner = CloudflareR2Provisioner(args.account_id, token)
    env_path = Path(args.env_file or config_path.with_name(".env"))
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                existing[key.strip()] = value.strip()
    try:
        result = provisioner.provision(
            bucket,
            token_name=args.token_name,
            existing_credentials=(existing.get("R2_ACCESS_KEY_ID", ""), existing.get("R2_SECRET_ACCESS_KEY", "")),
        )
        write_instance_r2_config(config_path, env_path, result)
    except R2ProvisioningError as exc:
        raise ConfigError(str(exc)) from exc
    print(f"R2 ready: bucket={result.bucket} account={result.account_id} created={result.bucket_created}")
    print(f"R2 credentials {'reused' if not result.token_created else 'written'} in {env_path}")
    return 0


def _cmd_design_experiment(args: argparse.Namespace) -> int:
    from .application.designs import DesignService
    from .core.design_contracts import BuildTarget, SiteIntake
    from .hands.builder import OperationRoutingBuilder
    from .hands.design_experiment import clone_public_repository, head_sha, remote_heads

    raw_env = load_env_file(args.env_file or ".env", dict(os.environ))
    experiment_env = DesignService.experiment_environment(raw_env)
    # Config validation needs to see that enabled instance integrations are
    # configured. The raw values stay in this parent process; all experiment
    # children and providers receive only the sanitized environment below.
    # The experiment child receives only the model credential. Optional
    # instance integrations remain disabled in the child, so their credentials
    # must not prevent an isolated design run from starting.
    config, _ = load(args.config, raw_env, validate_integrations=False)
    try:
        intake = (
            SiteIntake.from_dict(json.loads(Path(args.intake).read_text(encoding="utf-8")))
            if args.intake else None
        )
    except (OSError, TypeError, ValueError) as exc:
        raise DesignExperimentError(f"invalid design intake: {exc}") from exc
    lab_root = Path(args.data_dir).expanduser().resolve()
    clone_root = Path(args.experiment_root or (lab_root / "clone")).expanduser().resolve()
    config = copy.deepcopy(config)
    config["data_dir"] = str(lab_root / "data")
    llm = dict(config.get("llm") or {})
    engine = dict(config.get("design_engine") or {})
    design_model = str(engine.get("model") or llm.get("model") or DEEPSEEK_DESIGN_MODEL).strip()
    design_provider = str(engine.get("provider") or llm.get("provider") or "openrouter").strip()
    config["llm"] = {**llm, "model": design_model}
    engine["enabled"] = True
    engine["model"] = design_model
    engine["provider"] = design_provider
    engine["repair_attempts"] = int(engine.get("repair_attempts", 0))
    quality = dict(engine.get("quality") or {})
    quality["allowed_patterns"] = ["index.html", "styles.css", "app.js", "images/**", "design/**"]
    quality["required_pages"] = ["index.html", "articles.html"]
    quality["browser"] = True
    engine["quality"] = quality
    config["design_engine"] = engine
    config["builder"] = {
        **dict(config.get("builder") or {}),
        "enabled": True,
        "validation_repair_attempts": engine["repair_attempts"],
    }
    memory = Memory(Path(config["data_dir"]) / "design.db")
    run_id = ""
    try:
        service = DesignService(
            memory,
            config=config,
            output_artifact_store=SiteOutputArtifactStore(lab_root / "output-artifacts"),
        )
        service.validate_experiment_root(clone_root)
        clone = clone_public_repository(
            str((config.get("site") or {}).get("repository") or ""),
            clone_root,
            branch=str((config.get("site") or {}).get("branch") or "main"),
            progress=lambda message: print(f"[design-experiment] {message}"),
        )
        before_refs = remote_heads(clone)
        baseline_sha = head_sha(clone, str((config.get("site") or {}).get("branch") or "main"))
        run = service.create_experiment(
            intake,
            experiment_root=clone,
            base_sha=baseline_sha,
        )
        run_id = run["run_id"]
        request = service.prepare_initial_request(run["run_id"])
        target = BuildTarget.from_dict({
            "mode": "local_experiment",
            "repository": str((config.get("site") or {}).get("repository") or ""),
            "clone_path": str(clone),
            "base_sha": baseline_sha,
            "candidate_ref": run["candidate_ref"],
            "push_mode": "none",
            "publishable": False,
            "allowed_paths": quality["allowed_patterns"],
        })
        from .hands.playwright_quality import PlaywrightQualityAdapter

        browser = PlaywrightQualityAdapter(
            lab_root / "screenshots" / run["run_id"],
            variant="deepseek",
            routes=quality["required_pages"],
        )
        builder = NativeOpenCodeBuilder({
            "config": config,
            "memory": memory,
            "env": experiment_env,
            "browser_quality": browser,
        })
        service.builder = builder
        service.execute_build(run["run_id"], request, target, progress=lambda message: print(f"[design-experiment] {message}"))
        report = service.validate_run(run["run_id"], clone, browser=browser)
        visual_critique = None
        if report.state == "passed" and quality.get("visual_critic"):
            visual_critique = service.visual_review_run(run["run_id"], env=experiment_env)
        after_refs = remote_heads(clone)
        result = {
            "run": service.get_run(run["run_id"]),
            "quality_report": report.to_dict(),
            "visual_critique": visual_critique.to_dict() if visual_critique is not None else None,
            "baseline_sha": baseline_sha,
            "remote_refs_unchanged": before_refs == after_refs,
            "production_approval": False,
            "publishable": False,
            "push_mode": "none",
            "design_url": f"/ada/?design_run_id={run['run_id']}",
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if report.state == "passed" and (visual_critique is None or visual_critique.state == "passed") and before_refs == after_refs else 1
    except (DesignServiceError, DesignExperimentError) as exc:
        diagnostic: dict[str, object] = {"error": str(exc)}
        if run_id:
            diagnostic["run_id"] = run_id
            try:
                diagnostic["run"] = service.get_run(run_id)
            except Exception:
                pass
        print(json.dumps(diagnostic, indent=2, sort_keys=True, default=str), file=sys.stderr)
        return 1
    finally:
        memory.close()


def _loopback_host(host: str) -> bool:
    value = str(host or "").strip().lower().strip("[]")
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _intake_advisor_client(config: dict, memory, env: dict[str, str]):
    """A dedicated LLM client for the intake advisor when the instance routes it
    to a separate provider (design_engine.intake_advisor.base_url + api_key_env).
    Research, genesis, infusion, and the builder keep using the main client."""
    from .core.llm import Client

    advisor = dict((config.get("design_engine") or {}).get("intake_advisor") or {})
    base_url = str(advisor.get("base_url") or "").strip()
    api_key_env = str(advisor.get("api_key_env") or "").strip()
    if not base_url or not api_key_env:
        return None
    base_llm = dict(config.get("llm") or {})
    env_map = dict(config.get("env") or {})
    env_map["llm_api_key"] = api_key_env
    scoped = copy.deepcopy(config)
    scoped["env"] = env_map
    scoped["llm"] = {
        **base_llm,
        "base_url": base_url.rstrip("/"),
        "model": str(advisor.get("model") or base_llm.get("model") or "").strip(),
        "timeout_seconds": float(advisor.get("timeout_seconds") or base_llm.get("timeout_seconds") or 60),
        "max_retries": int(advisor.get("max_retries")
                           if advisor.get("max_retries") is not None
                           else base_llm.get("max_retries") or 2),
        "max_tokens": int(advisor.get("max_tokens") if advisor.get("max_tokens") else base_llm.get("max_tokens") or 0) or None,
        # Intake extraction is a bounded JSON turn.  Disable hidden reasoning
        # by default so a reasoning-heavy model cannot consume the whole output
        # budget before emitting the contract.  Providers that need a custom
        # thinking mode can opt back in explicitly.
        "enable_thinking": bool(advisor.get("enable_thinking", False)),
    }
    return Client(scoped, memory, env=env)


def _cmd_intake_lab(args: argparse.Namespace) -> int:
    from .application.design_intake import DesignIntakeService
    from .application.design_jobs import DesignJobExecutor
    from .application.designs import DesignService
    from .application.media import MediaService
    from .application.intake_lab import (
        IntakeLabError,
        IntakeLabService,
        build_intake_lab_build_environment,
        build_intake_lab_environment,
        validate_intake_lab_workspace,
    )
    from .application.incubations import IncubationApplicationService, IncubationRuntime
    from .application.incubation_activity import IncubationActivityService
    from .application.customer_genesis import CustomerGenesisService
    from .core.design_contracts import SiteIntake
    from .core.chat_jobs import ChatJobExecutor
    from .core.llm import Client
    from .core.intake_ada_store import IntakeAdaStore
    from .core.media_worker import MediaWorker
    from .core.vision import VisionClient
    from .hands.builder import NativeOpenCodeBuilder
    from .hands.local_media import LocalMediaStore
    from .hands.playwright_quality import PlaywrightQualityAdapter
    from .hands.site_build import SiteOutputArtifactStore
    from .web.intake_lab import create_app
    from .web.preview import LivePreviewStore, PreviewAccess, PreviewBuildCache

    if not _loopback_host(args.host):
        print("[site-agent] Intake Lab host must be a loopback address", file=sys.stderr)
        return 1
    if not 1 <= int(args.port) <= 65_535:
        print("[site-agent] Intake Lab port must be between 1 and 65535", file=sys.stderr)
        return 1

    raw_env = load_env_file(args.env_file or ".env", dict(os.environ))
    try:
        if args.intake:
            raise ConfigError("Intake Lab no longer accepts customer intake fixtures; create an incubation instead")
        config, _ = load_intake_config(args.config, raw_env, validate_integrations=False)
        workspace = validate_intake_lab_workspace(args.workspace, config)
    except (OSError, TypeError, ValueError, ConfigError) as exc:
        print(f"[site-agent] Intake Lab setup error: {exc}", file=sys.stderr)
        return 1

    config = copy.deepcopy(config)
    workspace.mkdir(parents=True, exist_ok=True)
    config["data_dir"] = str(workspace / "intake-ada-data")
    config["incubation"] = {
        **dict(config.get("incubation") or {}),
        "root": str(workspace / "incubations"),
        "scaffold": str(workspace / "neutral-scaffold"),
    }
    validate_intake_config(config)
    intake_settings = IntakeAdaSettings.from_config(config)
    preview_access = PreviewAccess(ttl=intake_settings.preview_ttl_seconds)
    from .brain.design_guidance import load_design_skills
    from .brain.incubation_research import LLMIncubationResearchPlanner

    design_skill_set = load_design_skills()
    engine = dict(config.get("design_engine") or {})
    engine["enabled"] = True
    engine["experiment_root"] = str(workspace / "runs")
    quality = dict(engine.get("quality") or {})
    quality["browser"] = True
    engine["quality"] = quality
    config["design_engine"] = engine
    builder_config = dict(config.get("builder") or {})
    builder_config["enabled"] = True
    config["builder"] = builder_config

    lock = AdminProcessLock(workspace / "intake-lab.lock")
    if not lock.acquire():
        print(f"[site-agent] Intake Lab workspace is already in use: {workspace}", file=sys.stderr)
        return 1

    memory = None
    intake_store = None
    incubations = None
    executor = None
    chat_executor = None
    media_worker = None
    try:
        intake_store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")

        def build_runtime(scoped):
            incubation_workspace = scoped.path.parent
            local_config = copy.deepcopy(config)
            local_config["data_dir"] = str(incubation_workspace / "data")
            local_engine = dict(local_config.get("design_engine") or {})
            local_engine["experiment_root"] = str(incubation_workspace / "runs")
            local_config["design_engine"] = local_engine
            local_environment = DesignService.experiment_environment(
                build_intake_lab_environment(local_config, raw_env, incubation_workspace)
            )
            local_build_environment = build_intake_lab_build_environment(local_config, raw_env, incubation_workspace)
            local_memory = scoped.memory
            local_activity = IncubationActivityService(local_memory)
            local_genesis = CustomerGenesisService(local_memory)
            local_llm = Client(local_config, local_memory, env=local_environment)
            local_intake_llm = _intake_advisor_client(local_config, local_memory, local_environment) or local_llm
            local_research_planner = LLMIncubationResearchPlanner(
                local_llm,
                local_config.get("research") or {},
            )
            local_runtime_context = {
                "config": local_config,
                "memory": local_memory,
                "env": local_environment,
                "design_skill_set": design_skill_set,
            }
            local_builder = OperationRoutingBuilder(local_runtime_context)
            local_design = DesignService(
                local_memory,
                config=local_config,
                builder=local_builder,
                skill_set=design_skill_set,
                output_artifact_store=SiteOutputArtifactStore(incubation_workspace / "output-artifacts"),
            )

            def local_browser_factory(run_id, run):
                run_intake = SiteIntake.from_dict(run.get("intake_json") or {})
                try:
                    routes = local_design.quality_policy_for_run(run_id).required_pages
                except Exception:
                    routes = run_intake.site.get("required_pages") or ()
                preview_variant = str(run.get("_preview_variant") or "candidate").strip().lower()
                if preview_variant not in {"candidate", "live"}:
                    preview_variant = "candidate"

                def owner_surface_url(route_name: str) -> str:
                    return (
                        f"http://{args.host}:{int(args.port)}/?incubation_id={quote(scoped.incubation_id)}"
                        f"&preview_run_id={quote(str(run_id), safe='')}"
                        f"&preview_variant={quote(preview_variant, safe='')}&preview_page={quote(str(route_name), safe='')}"
                    )

                return PlaywrightQualityAdapter(
                    incubation_workspace / "screenshots" / str(run_id),
                    variant=preview_variant,
                    routes=routes,
                    env=local_build_environment,
                    owner_surface_url_factory=owner_surface_url,
                    owner_surface_origin=f"http://{args.host}:{int(args.port)}",
                )

            def local_sighted_browser_factory(run_id, run):
                return local_browser_factory(
                    run_id,
                    {**dict(run), "_preview_variant": "live"},
                )

            local_runtime_context.update({
                "build_env": local_build_environment,
                "review_environment": local_environment,
                "browser_quality_factory": local_browser_factory,
                "sighted_browser_quality_factory": local_sighted_browser_factory,
                "recover_retained_candidates": True,
            })
            local_executor = DesignJobExecutor(local_runtime_context, local_design)
            live_preview_store = LivePreviewStore(incubation_workspace / "live-previews", retention=4)

            def checkpoint_live_preview(run_id: str, source_worktree: Path, label: str) -> dict[str, Any]:
                return live_preview_store.checkpoint(run_id, source_worktree, label=label)

            local_runtime_context["on_live_preview_checkpoint"] = checkpoint_live_preview
            local_runtime_context["on_sighted_preview_checkpoint"] = checkpoint_live_preview
            local_lab = IntakeLabService(
                local_design,
                local_executor,
                config=local_config,
                workspace=incubation_workspace,
                default_intake=None,
                default_prompt="Start by learning what the business offers, who it serves, and what visitors should do next.",
                review_environment=local_environment,
                live_preview_store=live_preview_store,
            )
            local_design_intake = DesignIntakeService(
                local_memory,
                config=local_config,
                llm=local_intake_llm,
                default_intake=None,
                design_service=local_design,
                lab_service=local_lab,
                media_url_prefix=f"./api/incubations/{scoped.incubation_id}/media",
                skill_set=design_skill_set,
                activity_service=local_activity,
                genesis_service=local_genesis,
                on_revision_saved=incubations.on_intake_revision(scoped.incubation_id),
            )
            # After a read-only visual review finishes, surface any imagery gaps
            # the review flagged (that the owner must supply) into the intake chat.
            local_executor.context["on_visual_review"] = local_design_intake.surface_review_asset_requests
            local_context = {
                "config": local_config,
                "memory": local_memory,
                "llm": local_llm,
                "env": local_environment,
                "build_env": local_build_environment,
                "design_service": local_design,
                "design_executor": local_executor,
                "design_intake_service": local_design_intake,
                "recover_retained_candidates": True,
                "design_skill_set": design_skill_set,
                "activity_service": local_activity,
            }
            local_context["on_intake_advice_complete"] = lambda job, result: incubations.auto_build_after_intake_turn(
                scoped.incubation_id,
                job,
                result,
            )
            local_chat = ChatJobExecutor(local_context)
            local_media_store = LocalMediaStore(incubation_workspace / "media")
            local_media_service = MediaService(local_memory, local_media_store, local_config)
            local_builder.context["media_store"] = local_media_store
            local_builder.context["media_service"] = local_media_service
            local_executor.context["media_store"] = local_media_store
            local_executor.context["media_service"] = local_media_service
            # The design service captures immutable visual evidence while it
            # freezes the run context.  Keep it on the same incubation-scoped
            # media service used by the builder; otherwise the specialist
            # planner sees only numeric asset inventory IDs and an empty
            # evidence set even though the builder can materialize the images.
            local_design.media_service = local_media_service
            local_context["media_store"] = local_media_store
            local_context["media_service"] = local_media_service
            local_analyzer = None
            vision_config = local_config.get("vision") or {}
            if vision_config.get("enabled"):
                local_vision = VisionClient(local_config, env=local_environment, memory=local_memory)
                if local_vision.api_key and local_vision.base_url and local_vision.model:
                    local_analyzer = local_vision
            local_context["media_analyzer"] = local_analyzer
            local_media_worker = MediaWorker(local_context)
            local_media_worker.on_analysis = lambda _asset_id, _analysis: incubations.schedule_infusion(
                scoped.incubation_id, "media_analyzed"
            )
            local_lab.media_service = local_media_service
            local_lab.media_worker = local_media_worker
            local_lab.design_intake_service = local_design_intake
            local_lab.chat_executor = local_chat
            local_design_intake.media_service = local_media_service
            return IncubationRuntime(
                design_service=local_design,
                executor=local_executor,
                intake_service=local_design_intake,
                lab_service=local_lab,
                chat_executor=local_chat,
                media_worker=local_media_worker,
                media_service=local_media_service,
                activity_service=local_activity,
                genesis_service=local_genesis,
                research_planner=local_research_planner,
                llm=local_llm,
            )

        incubations = IncubationApplicationService(
            intake_store,
            root=config["incubation"]["root"],
            config=config,
            runtime_factory=build_runtime,
        )
        incubation = incubations.get_or_create_default()
        default_store = incubations.open_store(incubation.incubation_id)
        memory = default_store.memory
        default_runtime = build_runtime(default_store)
        lab_service = default_runtime.lab_service
        executor = default_runtime.executor
        chat_executor = default_runtime.chat_executor
        media_worker = default_runtime.media_worker
        design_intake_service = default_runtime.intake_service
        incubations.attach_runtime(
            incubation.incubation_id,
            default_runtime,
        )
        build_environment = build_intake_lab_build_environment(config, raw_env, workspace)
        app = create_app(
            lab_service,
            workspace=workspace,
            preview_access=preview_access,
            preview_cache=PreviewBuildCache(
                build_env=build_environment,
                temp_root=workspace / ".preview-builds",
            ),
            incubation_service=incubations,
            default_incubation_id=incubation.incubation_id,
        )
        implementation = lab_service.describe()["implementation"]
        visual = lab_service.describe()["visual_review"]
        print(f"[site-agent] Intake Lab on http://{args.host}:{int(args.port)}")
        print(f"[site-agent] site={lab_service.describe()['site_name']}")
        print(f"[site-agent] implementation={implementation['provider']}:{implementation['model']}")
        print(f"[site-agent] visual_review={visual['provider']}:{visual['model']}")
        print(f"[site-agent] workspace={workspace}")
        import uvicorn

        uvicorn.run(app, host=args.host, port=int(args.port), log_level="warning")
        return 0
    except (IntakeLabError, ConfigError, OSError, ValueError) as exc:
        print(f"[site-agent] Intake Lab error: {exc}", file=sys.stderr)
        return 1
    finally:
        if chat_executor is not None:
            chat_executor.stop()
            chat_executor.join(timeout=10)
        if media_worker is not None:
            media_worker.stop()
            media_worker.join(timeout=10)
        if incubations is not None:
            incubations.close()
        elif memory is not None:
            memory.close()
        if intake_store is not None:
            intake_store.close()
        lock.release()


def _cmd_design_lab_generate(args: argparse.Namespace) -> int:
    from .core.design_contracts import SiteIntake

    raw_env = load_env_file(args.env_file or ".env", dict(os.environ))
    config, _ = load(args.config, raw_env)
    if args.model:
        config = copy.deepcopy(config)
        config["llm"] = {**dict(config.get("llm") or {}), "model": args.model}
    try:
        intake = SiteIntake.from_dict(json.loads(Path(args.intake).read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError) as exc:
        raise DesignLabError(f"invalid design intake: {exc}") from exc
    service = DesignLabService(
        config,
        args.workspace,
        env=raw_env,
        timeout_seconds=args.timeout,
    )
    result = service.generate(intake, browser=not args.no_browser, run_id=args.run_id)
    if not result["ok"]:
        print(f"[site-agent] design-lab failed: {result.get('error') or 'quality gates did not pass'}", file=sys.stderr)
        print(f"[site-agent] run={result['run_id']} report={result['artifacts']['reports']}", file=sys.stderr)
        return 1
    comparison_url = "(not started; use site-agent design-lab serve to reopen)"
    if not args.no_serve:
        comparison_url = f"http://{args.host}:{args.port}/?run={result['run_id']}"
    print(f"run_id: {result['run_id']}")
    print(f"baseline_sha: {result['baseline_sha']}")
    print(f"candidate_sha: {result['candidate_sha']}")
    print(f"model: {str((config.get('llm') or {}).get('model') or '')}")
    print(f"comparison_url: {comparison_url}")
    print("quality: passed")
    baseline_state = (result.get("quality") or {}).get("baseline_state")
    if baseline_state and baseline_state != "passed":
        print(f"baseline_quality: {baseline_state} (findings retained as non-blocking evidence)")
    print(f"workspace: {result['workspace']}")
    if not args.no_serve:
        from .web.design_lab import serve_design_lab

        try:
            serve_design_lab(args.workspace, result["run_id"], host=args.host, port=args.port)
        except KeyboardInterrupt:
            print("[site-agent] design-lab comparison server stopped")
    return 0


def _cmd_design_lab_serve(args: argparse.Namespace) -> int:
    from .web.design_lab import serve_design_lab

    DesignLabService.load_retained(args.workspace, args.run)
    print(f"comparison_url: http://{args.host}:{args.port}/?run={args.run}")
    try:
        serve_design_lab(args.workspace, args.run, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("[site-agent] design-lab comparison server stopped")
    return 0


def _cmd_design_lab_compare(args: argparse.Namespace) -> int:
    from .web.design_lab import serve_model_comparison

    print(f"comparison_url: http://{args.host}:{args.port}/")
    try:
        serve_model_comparison(args.manifest, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("[site-agent] model comparison server stopped")
    return 0


def _build_runtime(args: argparse.Namespace):
    from .core.llm import Client

    raw_env = dict(os.environ)
    config, _ = load(args.config, raw_env)
    # Tenant credentials are intentionally kept in the shared host profile.
    # Resolve them once after loading the tenant config and pass the resolved
    # environment to every trusted runtime adapter, including Payload.
    raw_env = credential_environment(config, raw_env)
    memory = Memory(data_dir(config) / "memory.db")
    ensure_default_goal(memory)
    llm = Client(config, memory, env=raw_env)
    scheduler = Scheduler(
        memory,
        lock_path=data_dir(config) / "scheduler.lock",
        timezone_name=growth_timezone(config),
    )
    runtime = Runtime(config, memory, scheduler, llm, effective_persona(config, memory))
    context = runtime.context()
    from .hands.payload_gateway import PayloadGatewayClient

    payload_gateway = PayloadGatewayClient.from_config(config, raw_env)
    if payload_gateway is not None:
        context["payload_gateway"] = payload_gateway
    site = config.get("site") or {}
    engine = config.get("design_engine") or {}
    builder_config = config.get("builder") or {}
    if (
        bool(engine.get("enabled"))
        and bool(builder_config.get("enabled"))
        and str(site.get("clone_path") or "").strip()
    ):
        from .core.design_contracts import SiteIntake
        from .hands.playwright_quality import PlaywrightQualityAdapter

        build_env = DesignService.experiment_environment(raw_env)
        context.update({
            "env": build_env,
            "build_env": build_env,
            "review_environment": build_env,
        })
        design_service = context.get("design_service")
        if design_service is not None:
            context["design_service"].builder = OperationRoutingBuilder(context)

            def browser_factory(run_id, run):
                try:
                    routes = design_service.quality_policy_for_run(run_id).required_pages
                except Exception:
                    intake = SiteIntake.from_dict(run.get("intake_json") or {})
                    routes = intake.site.get("required_pages") or ()
                return PlaywrightQualityAdapter(
                    data_dir(config) / "screenshots" / str(run_id),
                    variant="candidate",
                    routes=routes,
                    env=build_env,
                )

            context["browser_quality_factory"] = browser_factory
    if bool((config.get("activation") or {}).get("enabled", True)):
        register_builtin(scheduler, config, context)
    return config, memory, scheduler, context


def _cmd_once(args: argparse.Namespace) -> int:
    config, memory, scheduler, context = _build_runtime(args)
    runtime = context.get("runtime")
    try:
        if not scheduler.acquire_lock():
            print("[site-agent] another cycle is already running; skipping", file=sys.stderr)
            return 1
        try:
            if runtime is not None:
                runtime.start()
            ran = scheduler.run_once()
            print(f"[site-agent] instance={config['instance_name']} jobs ran: {ran or '(none due)'}")
            spend = memory.llm_spend()
            print(
                f"[site-agent] 24h llm spend: ${spend['cost_usd']:.4f} "
                f"({spend['prompt_tokens']} in / {spend['completion_tokens']} out)"
            )
        finally:
            scheduler.release_lock()
    finally:
        if runtime is not None:
            runtime.close()
        memory.close()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config, memory, scheduler, context = _build_runtime(args)
    runtime = context.get("runtime")
    poll = int(config.get("poll_seconds", 300))
    print(f"[site-agent] instance={config['instance_name']} polling every {poll}s")
    try:
        if not scheduler.acquire_lock():
            print("[site-agent] another cycle is already running", file=sys.stderr)
            return 1
        try:
            if runtime is not None:
                runtime.start()
            import time

            while True:
                scheduler.run_once()
                time.sleep(poll)
        finally:
            scheduler.release_lock()
    except KeyboardInterrupt:
        print("[site-agent] shutting down")
    finally:
        if runtime is not None:
            runtime.close()
        memory.close()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    print("[site-agent] the human-facing FastAPI admin is retired; open the customer Payload /admin workspace instead", file=sys.stderr)
    return 2


def _cmd_api(args: argparse.Namespace) -> int:
    """Serve the shared tenant-aware Ada API without a customer admin process."""
    import uvicorn

    from .application.tenant_registration import TenantRegistrationService
    from .application.bootstrap import WebsiteBootstrapService
    from .application.workspace import TenantRegistry
    from .web.workspace import create_workspace_api_app

    raw_env = dict(os.environ)
    config, _ = load(args.config, raw_env)
    raw_env = credential_environment(config, raw_env)
    registry = TenantRegistry.from_config(config, raw_env)
    registration = TenantRegistrationService(config, raw_env, registry=registry)
    bootstrap = WebsiteBootstrapService(config, raw_env, registration=registration, registry=registry)
    api = config.get("workspace_api") or {}
    app = create_workspace_api_app(
        registry,
        prefix=str(api.get("prefix") or "/v1/workspace"),
        control_token=raw_env.get("HELLOADA_CONTROL_PLANE_TOKEN"),
        registration=registration,
        bootstrap=bootstrap,
    )
    host = str(api.get("host") or "127.0.0.1")
    port = int(api.get("port") or 3014)
    print(f"[site-agent] shared Ada API on http://{host}:{port}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        bootstrap.close()
        registry.close()
    return 0


def _cmd_adopt_release_readiness(args: argparse.Namespace) -> int:
    """Record the explicit adoption of an existing, exactly verified tenant release."""
    from .application.bootstrap import BootstrapError, WebsiteBootstrapService
    from .application.tenant_registration import TenantRegistrationService
    from .application.workspace import TenantRegistry

    raw_env = dict(os.environ)
    config, _ = load(args.config, raw_env)
    raw_env = credential_environment(config, raw_env)
    registry = TenantRegistry.from_config(config, raw_env)
    registration = TenantRegistrationService(config, raw_env, registry=registry)
    bootstrap = WebsiteBootstrapService(config, raw_env, registration=registration, registry=registry)
    try:
        repository_root = Path(__file__).resolve().parents[2]
        verifier = repository_root / "scripts" / "deploy-payload-customer.py"
        if not verifier.is_file():
            print("[site-agent] canonical customer release verifier is unavailable; adoption stopped", file=sys.stderr)
            return 1
        try:
            verification = subprocess.run(
                [
                    sys.executable,
                    str(verifier),
                    "--tenant",
                    args.tenant,
                    "--ref",
                    args.source_sha,
                    "--release-id",
                    args.release_id,
                    "--verify-only",
                ],
                cwd=repository_root,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            print("[site-agent] current Worker verification did not complete; adoption was not written", file=sys.stderr)
            return 1
        if verification.returncode != 0:
            print("[site-agent] current Worker verification failed; adoption was not written", file=sys.stderr)
            return 1
        result = bootstrap.adopt_verified_release(
            args.tenant,
            release_id=args.release_id,
            source_sha=args.source_sha,
            worker_version=args.worker_version,
        )
        print(json.dumps({
            "tenant": args.tenant,
            "releaseId": args.release_id,
            "sourceSha": args.source_sha,
            "workerVersion": args.worker_version,
            "workspaceReady": result["workspace_ready"],
            "status": result["status"],
        }, indent=2))
        return 0
    except BootstrapError as exc:
        print(f"[site-agent] release adoption stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        bootstrap.close()
        registry.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="site-agent", description="Portable AI website content manager")
    parser.add_argument("--version", action="version", version=f"site-agent {__version__}")
    parser.add_argument("--config", help="path to instance config.yaml")
    common = argparse.ArgumentParser(add_help=False)
    # Do not let a subcommand's absent option overwrite a global option that
    # appeared before the subcommand: both CLI forms are documented.
    common.add_argument("--config", default=argparse.SUPPRESS, help="path to instance config.yaml")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", parents=[common], help="print resolved merged config with secrets masked")
    sub.add_parser("once", parents=[common], help="run all due jobs and exit")
    sub.add_parser("run", parents=[common], help="run the scheduler loop (long-lived)")
    sub.add_parser("serve", parents=[common], help="retired legacy admin command; use the customer Payload /admin workspace")
    sub.add_parser("api", parents=[common], help="run the shared tenant-aware Ada API")
    adopt_parser = sub.add_parser(
        "adopt-release-readiness",
        parents=[common],
        help="explicitly adopt an already deployed registered tenant into HelloAda admin readiness",
    )
    adopt_parser.add_argument("--tenant", required=True, help="registered tenant ID")
    adopt_parser.add_argument("--release-id", required=True, help="exact canonical VPS release ID")
    adopt_parser.add_argument("--source-sha", required=True, help="exact full 40-character customer source SHA")
    adopt_parser.add_argument("--worker-version", required=True, help="exact active Cloudflare Worker version ID")
    init_parser = sub.add_parser("init-site", help="create the canonical Next.js/Payload site in an empty site directory")
    init_parser.add_argument("--directory", required=True, help="empty customer website directory")
    init_parser.add_argument("--name", default="New Website", help="customer website name")
    init_parser.add_argument("--url", default="", help="public website URL")
    r2_parser = sub.add_parser("provision-r2", parents=[common], help="create a private customer-scoped Cloudflare R2 bucket and credential")
    r2_parser.add_argument("--instance", required=True, help="stable lowercase customer instance slug")
    r2_parser.add_argument("--account-id", required=True, help="Cloudflare account ID")
    r2_parser.add_argument("--bucket", help="R2 bucket name; defaults to helloada-<instance>-media")
    r2_parser.add_argument("--token-name", help="Cloudflare R2 token display name")
    r2_parser.add_argument("--env-file", help="instance env file; defaults beside config.yaml")
    r2_parser.add_argument("--bootstrap-env-file", help="global provisioning env file; defaults to .env in the current directory")
    seo_parser = sub.add_parser(
        "provision-seo",
        parents=[common],
        help="provision GA4, Search Console, and a CrawlSEO project for one tenant",
    )
    seo_parser.add_argument("--tenant", required=True, help="tenant slug; also the CrawlSEO external project id")
    seo_parser.add_argument("--domain", required=True, help="bare domain to verify and track")
    seo_parser.add_argument("--project-name", default="", help="display name for the GA4 property and project")
    seo_parser.add_argument("--organization", default="helloada", help="external organization id")
    seo_parser.add_argument("--site-url", default="", help="public site URL for the GA4 web stream")
    seo_parser.add_argument("--gsc-property", default="", help="Search Console property; defaults to sc-domain:<domain>")
    seo_parser.add_argument("--ga4-property-id", default="", help="reuse an existing GA4 property instead of creating one")
    seo_parser.add_argument("--time-zone", default="UTC")
    seo_parser.add_argument("--currency", default="EUR")
    seo_parser.add_argument("--no-verify-gsc", action="store_true", help="skip verification and property creation")
    seo_parser.add_argument("--verification-method", choices=("dns_txt", "meta"), default="dns_txt",
                            help="dns_txt for zones we control, meta for pages we serve (workers.dev)")
    seo_parser.add_argument("--verify-only", action="store_true",
                            help="complete a deferred meta verification; does not touch GA4 or CrawlSEO")
    seo_parser.add_argument("--domain-verification-method", default="verified_gsc")
    seo_parser.add_argument("--ensure-host", action="store_true", help="add a proxied placeholder A record when the host does not resolve")
    seo_parser.add_argument("--idempotency-key", default="", help="stable credential key; defaults to site-agent:<tenant>:v1")
    seo_parser.add_argument("--persist-token-dir", default="", help="directory for the 0600 crawlseo.env token file")
    email_parser = sub.add_parser(
        "provision-email",
        parents=[common],
        help="preflight or provision Cloudflare domain email for one registered tenant",
    )
    email_parser.add_argument("--tenant", required=True, help="stable tenant ID from the canonical tenants.json registry")
    email_parser.add_argument("--apply", action="store_true", help="enable the tenant email setting and apply the reviewed Cloudflare plan")
    email_parser.add_argument("--email-domain", default="", help="explicit Cloudflare-managed email domain; required for a workers.dev site without an existing email.domain setting")
    email_parser.add_argument("--local-part", default="", help="unique registered mailbox local part; persisted only with --apply")
    email_parser.add_argument(
        "--approve-mailgun-cutover",
        action="store_true",
        help="authorize replacing only apex mxa/mxb.mailgun.org MX and the exact standard Mailgun SPF record",
    )
    email_parser.add_argument(
        "--allow-forwarding-cutover",
        action="store_true",
        help="authorize replacing an exact-address Cloudflare forward rule with the tenant Worker rule",
    )
    experiment_parser = sub.add_parser("design-experiment", parents=[common], help="run a local-only immutable design experiment")
    experiment_parser.add_argument("--intake", required=True, help="sanitized design-intake JSON")
    experiment_parser.add_argument("--data-dir", required=True, help="dedicated experiment data directory")
    experiment_parser.add_argument("--experiment-root", help="dedicated clone path; defaults below --data-dir/clone")
    experiment_parser.add_argument("--env-file", help="optional environment file for model access")
    intake_lab_parser = sub.add_parser("intake-lab", parents=[common], help="serve the standalone local Intake Lab")
    intake_lab_parser.add_argument(
        "--intake",
        help=argparse.SUPPRESS,
    )
    intake_lab_parser.add_argument("--workspace", required=True, help="dedicated retained Intake Lab workspace")
    intake_lab_parser.add_argument("--env-file", help="optional environment file for model access")
    intake_lab_parser.add_argument("--host", default="127.0.0.1", help="loopback server host")
    intake_lab_parser.add_argument("--port", type=int, default=3012, help="loopback server port")
    design_lab = sub.add_parser("design-lab", help="run the disposable local design lab")
    design_lab_sub = design_lab.add_subparsers(dest="design_lab_command")
    generate_parser = design_lab_sub.add_parser("generate", parents=[common], help="generate and retain a local Next/React/Payload candidate")
    generate_parser.add_argument("--intake", required=True, help="sanitized design-intake JSON")
    generate_parser.add_argument("--workspace", required=True, help="disposable retained design-lab workspace")
    generate_parser.add_argument("--env-file", help="optional environment file for model access")
    generate_parser.add_argument("--model", help="per-run LLM model override; does not modify the instance config")
    generate_parser.add_argument("--run-id", help="optional retained run ID; must be unique within the workspace")
    generate_parser.add_argument("--no-browser", action="store_true", help="skip Chromium evidence (quality is still deterministic)")
    generate_parser.add_argument("--no-serve", action="store_true", help="retain artifacts without starting the comparison server")
    generate_parser.add_argument("--host", default="127.0.0.1", help="comparison server host")
    generate_parser.add_argument("--port", type=int, default=8765, help="comparison server port")
    generate_parser.add_argument("--timeout", type=int, default=900, help="per-build timeout in seconds")
    serve_parser = design_lab_sub.add_parser("serve", help="serve a retained design-lab run")
    serve_parser.add_argument("--workspace", required=True, help="retained design-lab workspace")
    serve_parser.add_argument("--run", required=True, help="retained run ID")
    serve_parser.add_argument("--host", default="127.0.0.1", help="comparison server host")
    serve_parser.add_argument("--port", type=int, default=8765, help="comparison server port")
    compare_parser = design_lab_sub.add_parser("compare", help="serve a read-only comparison of retained model candidates")
    compare_parser.add_argument("--manifest", required=True, help="model-comparison.json generated by the model matrix script")
    compare_parser.add_argument("--host", default="127.0.0.1", help="comparison server host")
    compare_parser.add_argument("--port", type=int, default=8765, help="comparison server port")

    args, unknown = parser.parse_known_args(argv)
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    if getattr(args, "config", None) is None:
        args.config = None
    handlers = {"check": _cmd_check, "once": _cmd_once, "run": _cmd_run, "serve": _cmd_serve, "api": _cmd_api,
                "adopt-release-readiness": _cmd_adopt_release_readiness,
                "init-site": _cmd_init_site,
                "provision-r2": _cmd_provision_r2, "provision-seo": _cmd_provision_seo,
                "provision-email": _cmd_provision_email,
                "design-experiment": _cmd_design_experiment, "intake-lab": _cmd_intake_lab}
    if args.command == "design-lab":
        handlers = {
            "design-lab-generate": _cmd_design_lab_generate,
            "design-lab-serve": _cmd_design_lab_serve,
            "design-lab-compare": _cmd_design_lab_compare,
        }
        if args.design_lab_command == "generate":
            args.command = "design-lab-generate"
        elif args.design_lab_command == "serve":
            args.command = "design-lab-serve"
        elif args.design_lab_command == "compare":
            args.command = "design-lab-compare"
        else:
            parser.error("design-lab requires generate or serve")
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except ConfigError as exc:
        print(f"[site-agent] configuration error: {exc}", file=sys.stderr)
        return 2
    except CrawlSEOError as exc:
        print(f"[site-agent] CrawlSEO provider error: {exc}", file=sys.stderr)
        return 1
    except (BuilderError, DesignExperimentError, DesignServiceError, DesignLabError) as exc:
        print(f"[site-agent] design error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
