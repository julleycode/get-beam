// Next.js 14 (<=15.2) browser init: withSentryConfig injects this file into the
// client bundle. Off when NEXT_PUBLIC_SENTRY_DSN is unset.
import { initSentry } from "./src/lib/sentry";

initSentry();
