import * as Sentry from "@sentry/nextjs";

import { initSentry } from "./lib/sentry";

initSentry();

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
