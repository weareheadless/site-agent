"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Plus, Search, UsersRound, X } from "lucide-react";
import { ContactDetailsTrigger } from "@/components/contacts/contact-details";
import { useLanguage } from "@/components/language-provider";
import { useSelectedMailbox } from "@/components/mailbox-provider";
import { authFetch } from "@/lib/auth/client";

type Contact = {
	id: string;
	email: string;
	displayName: string | null;
	source: "manual" | "inbound" | "outbound";
	blocked: boolean;
	lastSeenAt: string | null;
	createdAt: string;
};

export default function ContactsPage() {
	const { t } = useLanguage();
	const { selectedMailbox } = useSelectedMailbox();
	const [contacts, setContacts] = useState<Contact[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");
	const [search, setSearch] = useState("");
	const [adding, setAdding] = useState(false);
	const [name, setName] = useState("");
	const [email, setEmail] = useState("");
	const [saving, setSaving] = useState(false);
	const [saveError, setSaveError] = useState("");

	const loadContacts = useCallback(async () => {
		if (!selectedMailbox?.id) {
			setContacts([]);
			setLoading(false);
			return;
		}
		setLoading(true);
		setError("");
		try {
			const response = await authFetch("/api/contacts/list?mailboxId=" + encodeURIComponent(selectedMailbox.id));
			if (!response.ok) throw new Error(t("contacts.loadFailed"));
			const result = await response.json() as { contacts: Contact[] };
			setContacts(result.contacts);
		} catch (loadError) {
			setError(loadError instanceof Error ? loadError.message : t("contacts.loadFailed"));
		} finally {
			setLoading(false);
		}
	}, [selectedMailbox?.id, t]);

	useEffect(() => {
		void loadContacts();
		const refresh = () => void loadContacts();
		window.addEventListener("mailflare:contact-changed", refresh);
		return () => window.removeEventListener("mailflare:contact-changed", refresh);
	}, [loadContacts]);

	const filteredContacts = useMemo(() => {
		const needle = search.trim().toLocaleLowerCase();
		if (!needle) return contacts;
		return contacts.filter((contact) =>
			(contact.displayName ?? "").toLocaleLowerCase().includes(needle)
			|| contact.email.toLocaleLowerCase().includes(needle),
		);
	}, [contacts, search]);

	async function addContact(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (!selectedMailbox?.id || !name.trim() || !email.trim()) return;
		setSaving(true);
		setSaveError("");
		try {
			const response = await authFetch("/api/contacts", {
				method: "PATCH",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					mailboxId: selectedMailbox.id,
					address: email.trim(),
					displayName: name.trim(),
				}),
			});
			if (!response.ok) throw new Error(t("contacts.saveFailed"));
			setName("");
			setEmail("");
			setAdding(false);
			await loadContacts();
		} catch (saveError) {
			setSaveError(saveError instanceof Error ? saveError.message : t("contacts.saveFailed"));
		} finally {
			setSaving(false);
		}
	}

	function activityLabel(value: string | null) {
		if (!value) return "—";
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return "—";
		return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
	}

	function sourceLabel(source: Contact["source"]) {
		if (source === "manual") return t("contacts.source.manual");
		if (source === "inbound") return t("contacts.source.inbound");
		return t("contacts.source.outbound");
	}

	return (
		<div className="flex h-full min-h-0 flex-col bg-[#f6f8fc]">
			<header className="shrink-0 border-b border-neutral-200/70 bg-white px-5 py-5 sm:px-7">
				<div className="mx-auto flex max-w-6xl flex-wrap items-start justify-between gap-4">
					<div className="min-w-0">
						<div className="flex items-center gap-2 text-sm font-medium text-orange-700">
							<UsersRound aria-hidden="true" className="h-4 w-4" />
							<span>{t("contacts.title")}</span>
						</div>
						<p className="mt-1 text-sm text-neutral-600">{t("contacts.description")}</p>
					</div>
					<button
						type="button"
						onClick={() => { setAdding((current) => !current); setSaveError(""); }}
						className="inline-flex h-10 items-center gap-2 rounded-full bg-orange-500 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-orange-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400 focus-visible:ring-offset-2"
					>
						{adding ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
						{adding ? t("contacts.cancel") : t("contacts.add")}
					</button>
				</div>
			</header>

			<main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-7">
				<div className="mx-auto max-w-6xl space-y-4">
					{adding && (
						<form onSubmit={(event) => void addContact(event)} className="grid gap-3 rounded-2xl border border-orange-200 bg-white p-4 shadow-sm sm:grid-cols-[1fr_1fr_auto] sm:items-end">
							<div>
								<label htmlFor="contact-name" className="mb-1.5 block text-xs font-semibold text-neutral-700">{t("contacts.name")}</label>
								<input id="contact-name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} autoComplete="name" className="h-10 w-full rounded-xl border border-neutral-200 bg-white px-3 text-sm text-neutral-900 outline-none transition focus:border-orange-400 focus:ring-2 focus:ring-orange-100" />
							</div>
							<div>
								<label htmlFor="contact-email" className="mb-1.5 block text-xs font-semibold text-neutral-700">{t("contacts.email")}</label>
								<input id="contact-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={254} autoComplete="email" className="h-10 w-full rounded-xl border border-neutral-200 bg-white px-3 text-sm text-neutral-900 outline-none transition focus:border-orange-400 focus:ring-2 focus:ring-orange-100" />
							</div>
							<button type="submit" disabled={saving || !selectedMailbox?.id} className="h-10 rounded-xl bg-neutral-900 px-5 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50">
								{saving ? t("contacts.saving") : t("contacts.save")}
							</button>
							{saveError && <p role="alert" className="text-sm text-red-600 sm:col-span-3">{saveError}</p>}
						</form>
					)}

					<div className="flex flex-wrap items-center justify-between gap-3">
						<p className="text-sm font-medium text-neutral-600">{contacts.length} {t("contacts.title").toLocaleLowerCase()}</p>
						<label className="relative block w-full sm:w-80">
							<Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
							<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("contacts.search")} aria-label={t("contacts.search")} className="h-10 w-full rounded-full border border-neutral-200 bg-white pl-9 pr-4 text-sm text-neutral-900 outline-none transition focus:border-orange-400 focus:ring-2 focus:ring-orange-100" />
						</label>
					</div>

					<section aria-label={t("contacts.title")} className="overflow-hidden rounded-2xl border border-neutral-200/80 bg-white shadow-sm">
						{loading ? (
							<div role="status" className="px-5 py-12 text-center text-sm text-neutral-500">{t("contacts.loading")}</div>
						) : error ? (
							<div role="alert" className="px-5 py-12 text-center text-sm text-red-600">{error}</div>
						) : filteredContacts.length === 0 ? (
							<div className="px-5 py-14 text-center">
								<div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-orange-50 text-orange-600"><UsersRound aria-hidden="true" className="h-5 w-5" /></div>
								<p className="mt-3 text-sm font-semibold text-neutral-900">{contacts.length === 0 ? t("contacts.empty") : t("contacts.noResults")}</p>
								{contacts.length === 0 && <p className="mt-1 text-sm text-neutral-500">{t("contacts.emptyDescription")}</p>}
							</div>
						) : (
							<ul className="divide-y divide-neutral-100">
								{filteredContacts.map((contact) => (
									<li key={contact.id} className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2 px-4 py-4 transition-colors hover:bg-orange-50/30 sm:px-5">
										<div className="min-w-0 flex-1">
											<ContactDetailsTrigger
												mailboxId={selectedMailbox?.id ?? ""}
												address={contact.email}
												name={contact.displayName || contact.email}
												className="block max-w-full truncate text-left text-sm font-semibold text-neutral-900"
											/>
											<p className="mt-0.5 truncate text-sm text-neutral-500">{contact.email}</p>
										</div>
										<div className="flex shrink-0 items-center gap-5 text-xs text-neutral-500">
											<span className="rounded-full bg-neutral-100 px-2.5 py-1 font-medium text-neutral-600">{sourceLabel(contact.source)}</span>
											<span className="hidden min-w-28 text-right sm:block">{t("contacts.lastActivity")}: {activityLabel(contact.lastSeenAt)}</span>
										</div>
									</li>
								))}
							</ul>
						)}
					</section>
				</div>
			</main>
		</div>
	);
}
