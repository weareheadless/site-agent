import { registerHooks } from "node:module";

const timeUtils = new URL("../upstream/src/lib/time/utils.ts", import.meta.url).href;
const bookingService = new URL("../../../src/site_agent/templates/next-payload/mailflare-booking-service.ts", import.meta.url).href;

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@/lib/time/utils") return { url: timeUtils, shortCircuit: true };
    if (specifier === "@/lib/helloada-booking-service") return { url: bookingService, shortCircuit: true };
    return nextResolve(specifier, context);
  },
});
