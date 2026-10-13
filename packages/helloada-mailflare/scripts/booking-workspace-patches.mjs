import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const replaceOnce = (source, before, after, label) => {
  const first = source.indexOf(before);
  if (first < 0 || source.indexOf(before, first + before.length) !== -1) {
    throw new Error("Booking workspace patch did not match exactly once: " + label);
  }
  return source.slice(0, first) + after + source.slice(first + before.length);
};

const removeSection = (source, start, end, label) => {
  const first = source.indexOf(start);
  const endAt = source.indexOf(end, first + start.length);
  if (first < 0 || endAt < 0 || source.indexOf(start, first + start.length) !== -1) {
    throw new Error("Booking workspace section did not match exactly once: " + label);
  }
  return source.slice(0, first) + source.slice(endAt + end.length);
};

export async function applyBookingWorkspacePatches(destination) {
  const src = path.join(destination, "src");
  const settingsNavPath = path.join(src, "components/settings/settings-nav-utils.ts");
  let settingsNav = await readFile(settingsNavPath, "utf8");
  settingsNav = replaceOnce(settingsNav,
    '\t\t\t{\n\t\t\t\thref: "/settings/inbox",\n\t\t\t\tlabelKey: "settings.nav.inbox",\n\t\t\t},',
    '\t\t\t{\n\t\t\t\thref: "/settings/inbox",\n\t\t\t\tlabelKey: "settings.nav.inbox",\n\t\t\t},\n\t\t\t{\n\t\t\t\thref: "/settings/bookings",\n\t\t\t\tlabelKey: "booking.title",\n\t\t\t},',
    "Settings navigation");
  await writeFile(settingsNavPath, settingsNav);

  const dashboardNavPath = path.join(src, "components/dashboard-nav.tsx");
  let dashboardNav = await readFile(dashboardNavPath, "utf8");
  dashboardNav = replaceOnce(dashboardNav, '  CalendarClock,\n', '  CalendarClock,\n  CalendarDays,\n', "Calendar navigation icon");
  dashboardNav = replaceOnce(dashboardNav,
    '  { href: "/inbox", labelKey: "navigation.inbox", icon: Inbox, preloadMessages: true },',
    '  { href: "/inbox", labelKey: "navigation.inbox", icon: Inbox, preloadMessages: true },\n  { href: "/calendar", labelKey: "calendar.calendar", icon: CalendarDays },',
    "Calendar application navigation");
  await writeFile(dashboardNavPath, dashboardNav);

  const calendarLayoutPath = path.join(src, "app/(calendar)/layout.tsx");
  let calendarLayout = await readFile(calendarLayoutPath, "utf8");
  calendarLayout = replaceOnce(calendarLayout, 'import { CalendarMobileUpcoming } from "./calendar-mobile-upcoming";', 'import { DashboardNav } from "@/components/dashboard-nav";', "Calendar sidebar import");
  calendarLayout = replaceOnce(calendarLayout,
    '<div className="grid h-dvh grid-cols-[minmax(0,1fr)] overflow-hidden bg-[#f6f8fc]">',
    '<div className="grid h-dvh grid-cols-[minmax(0,1fr)] overflow-hidden bg-[#f6f8fc] md:grid-cols-[var(--sidebar-width)_minmax(0,1fr)]">',
    "Calendar workspace grid");
  calendarLayout = replaceOnce(calendarLayout, '<SidebarAside className="md:hidden"><CalendarMobileUpcoming /></SidebarAside>', '<SidebarAside><DashboardNav /></SidebarAside>', "Calendar persistent sidebar");
  calendarLayout = replaceOnce(calendarLayout,
    '<div className="min-w-0 flex-1 basis-0 md:hidden"><div className="relative w-fit max-w-full"><select aria-label={t("calendar.sectionLabel")} value={pathname === "/booking" ? "/booking" : "/calendar"} onChange={(event) => router.push(event.target.value)} className="h-8 max-w-full appearance-none rounded-full border-0 bg-white pl-3 pr-8 text-sm font-medium text-neutral-700"><option value="/booking">{t("calendar.bookings")}</option><option value="/calendar">{t("calendar.calendar")}</option></select><ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-600" /></div></div>',
    '<div className="min-w-0 flex-1 md:hidden" />',
    "Calendar mobile route selector");
  calendarLayout = removeSection(calendarLayout,
    '<nav aria-label={t("calendar.sections")} className="flex shrink-0 max-md:hidden items-center rounded-full bg-white p-1">',
    '</nav>',
    "Calendar operational tabs");
  calendarLayout = replaceOnce(calendarLayout, 'import { ChevronDown, Sparkles } from "lucide-react";', 'import { Sparkles } from "lucide-react";', "Calendar layout icons");
  calendarLayout = replaceOnce(calendarLayout, 'import Link from "next/link";\n', "", "Calendar layout Link import");
  calendarLayout = replaceOnce(calendarLayout, 'import { usePathname, useRouter } from "next/navigation";', "", "Calendar layout navigation import");
  calendarLayout = replaceOnce(calendarLayout, '  const pathname = usePathname();\n', "", "Calendar layout pathname");
  calendarLayout = replaceOnce(calendarLayout, '  const router = useRouter();\n', "", "Calendar layout router");
  await writeFile(calendarLayoutPath, calendarLayout);

  const bookingRoute = path.join(src, "app/(calendar)/booking/page.tsx");
  await writeFile(bookingRoute,
    'import { redirect } from "next/navigation";\n\nexport default function BookingSettingsRedirect() {\n  redirect("/settings/bookings");\n}\n');

  const settingsDir = path.join(src, "app/(settings)/settings/bookings");
  await mkdir(settingsDir, { recursive: true });
  await writeFile(path.join(settingsDir, "page.tsx"),
    'import { BusinessBookingSettings } from "@/components/booking/business-settings";\nimport { BusinessBookingTypes } from "@/components/booking/business-types";\n\nexport default function BookingSettingsPage() {\n  return <div className="space-y-8"><BusinessBookingSettings /><BusinessBookingTypes /></div>;\n}\n');
}
