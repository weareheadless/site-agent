import { desc, eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { getDb } from "@/db";
import { contacts } from "@/db/schema";
import { requireUser } from "@/lib/auth/cookies";
import { getEnv } from "@/lib/cloudflare";
import { getMailboxAccessLevel } from "@/lib/mailboxes/access";

export async function GET(request: Request) {
	const env = getEnv();
	const user = await requireUser(env, request);
	const mailboxId = new URL(request.url).searchParams.get("mailboxId")?.trim();
	if (!mailboxId) {
		return NextResponse.json({ error: "A mailbox is required" }, { status: 400 });
	}

	const db = getDb(env);
	const access = await getMailboxAccessLevel(db, user, mailboxId);
	if (!access?.canRead) {
		return NextResponse.json({ error: "Mailbox not found" }, { status: 404 });
	}

	const items = await db
		.select({
			id: contacts.id,
			email: contacts.email,
			displayName: contacts.displayName,
			source: contacts.source,
			blocked: contacts.blocked,
			lastSeenAt: contacts.lastSeenAt,
			createdAt: contacts.createdAt,
		})
		.from(contacts)
		.where(eq(contacts.userId, access.mailbox.userId))
		.orderBy(desc(contacts.lastSeenAt), desc(contacts.createdAt));

	return NextResponse.json({ contacts: items });
}
