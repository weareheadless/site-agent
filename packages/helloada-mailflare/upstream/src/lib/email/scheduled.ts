import { and, eq, exists, isNotNull } from "drizzle-orm";
import type { SQL } from "drizzle-orm";
import { getDb } from "@/db";
import { messages, outboundJobs } from "@/db/schema";

/** Matches outbound messages whose send job is still waiting for its scheduled time. */
export function scheduledMessageCondition(db: ReturnType<typeof getDb>): SQL {
	return and(
		eq(messages.direction, "outbound"),
		eq(messages.status, "queued"),
		exists(
			db
				.select({ id: outboundJobs.id })
				.from(outboundJobs)
				.where(and(eq(outboundJobs.messageId, messages.id), eq(outboundJobs.status, "queued"), isNotNull(outboundJobs.scheduledAt))),
		),
	)!;
}
