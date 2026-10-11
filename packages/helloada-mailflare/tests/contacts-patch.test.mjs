import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { applyContactsPatch, patchDashboardNavigation, patchLocale } from "../scripts/contacts-patch.mjs";

const dashboardNav = [
	'import {',
	'  MailPlus,',
	'  Trash2,',
	'  CalendarClock',
	'} from "lucide-react";',
	'const links = [',
	'  { href: "/compose", labelKey: "navigation.compose", icon: MailPlus, primary: true },',
	'  { href: "/inbox", labelKey: "navigation.inbox", icon: Inbox, preloadMessages: true },',
	'];',
].join("\n");

test("adds first-class Contacts and Calendar links to the shared mailbox navigation", () => {
	const result = patchDashboardNavigation(dashboardNav);
	assert.match(result, /UsersRound/);
	assert.match(result, /CalendarClock/);
	assert.match(result, /href: "\/contacts".*navigation\.contacts/);
	assert.match(result, /href: "\/calendar".*navigation\.calendar/);
});

test("fails closed when the pinned navigation shape changes", () => {
	assert.throws(() => patchDashboardNavigation(dashboardNav.replace('href: "/compose"', 'href: "/write"')), /no longer applies exactly once/);
});

test("adds localizable labels without changing existing translations", () => {
	const source = JSON.stringify({ "navigation.compose": "Compose" });
	const patched = JSON.parse(patchLocale(source, "fr"));
	assert.equal(patched["navigation.contacts"], "Contacts");
	assert.equal(patched["navigation.calendar"], "Calendrier");
	assert.equal(patched["navigation.compose"], "Compose");
});

test("copies an authenticated, tenant-scoped Contacts list and API into the disposable build", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "helloada-contacts-test-"));
	try {
		await mkdir(path.join(root, "src/components"), { recursive: true });
		await mkdir(path.join(root, "src/lib/i18n"), { recursive: true });
		await mkdir(path.join(root, "public/locales"), { recursive: true });
		await writeFile(path.join(root, "src/components/dashboard-nav.tsx"), dashboardNav);
		await writeFile(path.join(root, "src/lib/i18n/en.json"), JSON.stringify({ "navigation.compose": "Compose" }));
		await writeFile(path.join(root, "public/locales/fr.json"), JSON.stringify({ "navigation.compose": "Écrire" }));
		await writeFile(path.join(root, "public/locales/es.json"), JSON.stringify({ "navigation.compose": "Redactar" }));

		await applyContactsPatch(root);

		const page = await readFile(path.join(root, "src/app/(dashboard)/contacts/page.tsx"), "utf8");
		const route = await readFile(path.join(root, "src/app/api/contacts/list/route.ts"), "utf8");
		const nav = await readFile(path.join(root, "src/components/dashboard-nav.tsx"), "utf8");
		assert.match(page, /ContactDetailsTrigger/);
		assert.match(page, /authFetch\("\/api\/contacts\/list/);
		assert.match(route, /requireUser/);
		assert.match(route, /getMailboxAccessLevel/);
		assert.match(route, /access\?\.canRead/);
		assert.match(nav, /href: "\/calendar"/);
	} finally {
		await rm(root, { recursive: true, force: true });
	}
});
