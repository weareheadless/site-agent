import assert from "node:assert/strict";
import test from "node:test";
import { applyMailboxAvailabilityPatch } from "../scripts/mailbox-availability-patch.mjs";

const meRoute = [
	'import { getEnv } from "@/lib/cloudflare";',
	'import { hasPrimaryDomain, userHasMailboxes } from "@/lib/user";',
	"",
	"export async function GET(request: Request) {",
	"\tconst env = getEnv();",
	"\tconst [hasMailboxes, isSetup] = await Promise.all([",
	"\t\tuserHasMailboxes(env, user.id),",
	"\t\thasPrimaryDomain(env),",
	"\t]);",
	"\treturn NextResponse.json({ hasMailboxes, isSetup });",
	"}",
].join("\n");

test("reports a shared workspace mailbox the owner was granted access to", () => {
	const patched = applyMailboxAvailabilityPatch(meRoute);
	assert.match(patched, /userHasAccessibleMailboxes\(env, user\)/);
	assert.doesNotMatch(patched, /userHasMailboxes/);
	assert.match(patched, /hasPrimaryDomain/);
});

test("fails closed when the pinned auth route shape changes", () => {
	assert.throws(
		() => applyMailboxAvailabilityPatch(meRoute.replace("userHasMailboxes(env, user.id),", "userHasMailboxes(env, user),")),
		/no longer applies exactly once/,
	);
});
