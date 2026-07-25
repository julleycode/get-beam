// Minimal ambient declaration for the chrome extension APIs the dashboard uses
// to talk to the Beam LinkedIn Outreach Connect extension. The repo has no
// @types/chrome and no other chrome-extension surface, so a local shape is
// preferred over pulling the full package (plan Touchpoints — @types/chrome gap).
//
// Declared on Window (optional) so referencing it is safe on browsers with no
// extension API (Firefox/Safari): `window.chrome` is simply undefined there.

interface BeamChromeRuntime {
  sendMessage(
    extensionId: string,
    message: unknown,
    responseCallback?: (response: unknown) => void
  ): void;
  lastError?: { message?: string };
}

interface BeamChrome {
  runtime?: BeamChromeRuntime;
}

interface Window {
  chrome?: BeamChrome;
}
