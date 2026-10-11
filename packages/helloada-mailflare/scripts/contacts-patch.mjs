import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function replaceExactlyOnce(source, before, after, filename) {
	const first = source.indexOf(before);
	if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
		throw new Error("Pinned HelloAda Contacts patch no longer applies exactly once: " + filename);
	}
	return source.slice(0, first) + after + source.slice(first + before.length);
}

export function patchDashboardNavigation(source) {
	let patched = replaceExactlyOnce(
		source,
		'  Trash2,\n} from "lucide-react";',
		'  Trash2,\n  UsersRound,\n  CalendarClock,\n} from "lucide-react";',
		"dashboard-nav.tsx Contacts icon",
	);
	patched = replaceExactlyOnce(
		patched,
		'  { href: "/compose", labelKey: "navigation.compose", icon: MailPlus, primary: true },',
		[
			'  { href: "/compose", labelKey: "navigation.compose", icon: MailPlus, primary: true },',
			'  { href: "/contacts", labelKey: "navigation.contacts", icon: UsersRound },',
			'  { href: "/calendar", labelKey: "navigation.calendar", icon: CalendarClock },',
		].join("\n"),
		"dashboard-nav.tsx Contacts and Calendar links",
	);
	return patched;
}

const translations = {
	en: {
		"navigation.contacts": "Contacts",
		"navigation.calendar": "Calendar",
		"contacts.title": "Contacts",
		"contacts.description": "Website enquiries and bookings are organized here automatically.",
		"contacts.search": "Search by name or email",
		"contacts.loading": "Loading contacts...",
		"contacts.saving": "Saving...",
		"contacts.add": "Add contact",
		"contacts.addTitle": "Add a contact",
		"contacts.name": "Name",
		"contacts.email": "Email address",
		"contacts.save": "Save contact",
		"contacts.cancel": "Cancel",
		"contacts.empty": "No contacts yet",
		"contacts.emptyDescription": "New website enquiries and bookings will appear here.",
		"contacts.noResults": "No contacts match your search.",
		"contacts.loadFailed": "Contacts could not be loaded.",
		"contacts.saveFailed": "The contact could not be saved.",
		"contacts.source": "Added from",
		"contacts.lastActivity": "Last activity",
		"contacts.source.manual": "You",
		"contacts.source.inbound": "Enquiry or booking",
		"contacts.source.outbound": "Email",
	},
	fr: {
		"navigation.contacts": "Contacts",
		"navigation.calendar": "Calendrier",
		"contacts.title": "Contacts",
		"contacts.description": "Les demandes du site et les réservations sont regroupées ici automatiquement.",
		"contacts.search": "Rechercher par nom ou e-mail",
		"contacts.loading": "Chargement des contacts…",
		"contacts.saving": "Enregistrement…",
		"contacts.add": "Ajouter un contact",
		"contacts.addTitle": "Ajouter un contact",
		"contacts.name": "Nom",
		"contacts.email": "Adresse e-mail",
		"contacts.save": "Enregistrer le contact",
		"contacts.cancel": "Annuler",
		"contacts.empty": "Aucun contact pour le moment",
		"contacts.emptyDescription": "Les nouvelles demandes du site et réservations apparaîtront ici.",
		"contacts.noResults": "Aucun contact ne correspond à la recherche.",
		"contacts.loadFailed": "Impossible de charger les contacts.",
		"contacts.saveFailed": "Impossible d’enregistrer le contact.",
		"contacts.source": "Ajouté depuis",
		"contacts.lastActivity": "Dernière activité",
		"contacts.source.manual": "Vous",
		"contacts.source.inbound": "Demande ou réservation",
		"contacts.source.outbound": "E-mail",
	},
	es: {
		"navigation.contacts": "Contactos",
		"navigation.calendar": "Calendario",
		"contacts.title": "Contactos",
		"contacts.description": "Las consultas del sitio y las reservas se organizan aquí automáticamente.",
		"contacts.search": "Buscar por nombre o correo",
		"contacts.loading": "Cargando contactos…",
		"contacts.saving": "Guardando…",
		"contacts.add": "Agregar contacto",
		"contacts.addTitle": "Agregar un contacto",
		"contacts.name": "Nombre",
		"contacts.email": "Correo electrónico",
		"contacts.save": "Guardar contacto",
		"contacts.cancel": "Cancelar",
		"contacts.empty": "Aún no hay contactos",
		"contacts.emptyDescription": "Aquí aparecerán las nuevas consultas y reservas del sitio.",
		"contacts.noResults": "Ningún contacto coincide con la búsqueda.",
		"contacts.loadFailed": "No se pudieron cargar los contactos.",
		"contacts.saveFailed": "No se pudo guardar el contacto.",
		"contacts.source": "Agregado desde",
		"contacts.lastActivity": "Última actividad",
		"contacts.source.manual": "Tú",
		"contacts.source.inbound": "Consulta o reserva",
		"contacts.source.outbound": "Correo",
	},
};

export function patchLocale(source, locale) {
	const additions = translations[locale];
	if (!additions) throw new Error("Unsupported HelloAda Contacts locale: " + locale);
	const values = JSON.parse(source);
	for (const [key, value] of Object.entries(additions)) {
		if (Object.hasOwn(values, key) && values[key] !== value) {
			throw new Error("Pinned HelloAda Contacts translation already exists with a different value: " + key);
		}
		values[key] = value;
	}
	return JSON.stringify(values, null, 2) + "\n";
}

export async function applyContactsPatch(destination) {
	const navigationPath = path.join(destination, "src/components/dashboard-nav.tsx");
	const navigation = await readFile(navigationPath, "utf8");
	await writeFile(navigationPath, patchDashboardNavigation(navigation));

	const localePaths = {
		en: path.join(destination, "src/lib/i18n/en.json"),
		fr: path.join(destination, "public/locales/fr.json"),
		es: path.join(destination, "public/locales/es.json"),
	};
	for (const [locale, filename] of Object.entries(localePaths)) {
		const source = await readFile(filename, "utf8");
		await writeFile(filename, patchLocale(source, locale));
	}

	const routeDirectory = path.join(destination, "src/app/(dashboard)/contacts");
	const apiDirectory = path.join(destination, "src/app/api/contacts/list");
	await mkdir(routeDirectory, { recursive: true });
	await mkdir(apiDirectory, { recursive: true });
	await copyFile(path.join(packageRoot, "contacts-ui/page.tsx"), path.join(routeDirectory, "page.tsx"));
	await copyFile(path.join(packageRoot, "contacts-ui/route.ts"), path.join(apiDirectory, "route.ts"));
}
