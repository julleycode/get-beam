export interface PlatformStep {
  title: string;
  description: string;
}

export interface PlatformGuide {
  id: string;
  name: string;
  installType: "oauth" | "plugin" | "gtm" | "manual";
  steps: PlatformStep[];
  note?: string;
}

export const platformGuides: Record<string, PlatformGuide> = {
  shopify: {
    id: "shopify",
    name: "Shopify",
    installType: "oauth",
    steps: [
      {
        title: "Connect your store",
        description: "Click the button below to connect your Shopify store.",
      },
      {
        title: "Authorize access",
        description:
          "You'll be redirected to Shopify to authorize the pixel installation.",
      },
      {
        title: "Done!",
        description:
          "The tracking pixel will be automatically added to all pages of your store.",
      },
    ],
  },
  wordpress: {
    id: "wordpress",
    name: "WordPress",
    installType: "plugin",
    steps: [
      {
        title: "Download the plugin",
        description: "Click the button below to download the pre-configured plugin.",
      },
      {
        title: "Upload to WordPress",
        description:
          'Go to your WordPress admin panel → Plugins → Add New → Upload Plugin → choose the .zip file.',
      },
      {
        title: "Activate",
        description:
          'Click "Activate" on the plugin. The pixel is now live on your site!',
      },
    ],
  },
  wix: {
    id: "wix",
    name: "Wix",
    installType: "manual",
    steps: [
      {
        title: "Open Wix Settings",
        description:
          "In your Wix dashboard, go to Settings (gear icon in the left sidebar).",
      },
      {
        title: "Go to Custom Code",
        description:
          'Scroll down and click "Custom Code" under the Advanced section.',
      },
      {
        title: "Add the code",
        description:
          'Click "+ Add Code", paste the snippet below, set placement to "Head" and apply to "All pages", then click "Apply".',
      },
    ],
  },
  squarespace: {
    id: "squarespace",
    name: "Squarespace",
    installType: "manual",
    steps: [
      {
        title: "Open Code Injection",
        description: "Go to Settings → Advanced → Code Injection.",
      },
      {
        title: "Paste the code",
        description: 'Paste the snippet below into the "Header" box.',
      },
      {
        title: "Save",
        description: 'Click "Save" at the top. The pixel is now active!',
      },
    ],
  },
  webflow: {
    id: "webflow",
    name: "Webflow",
    installType: "manual",
    steps: [
      {
        title: "Open Project Settings",
        description: "In Webflow Designer, go to Project Settings (gear icon).",
      },
      {
        title: "Add Custom Code",
        description:
          'Go to the "Custom Code" tab and paste the snippet below in the "Head Code" section.',
      },
      {
        title: "Publish",
        description:
          "Click Save, then publish your site for the changes to go live.",
      },
    ],
  },
  unknown: {
    id: "unknown",
    name: "Your Website",
    installType: "manual",
    steps: [
      {
        title: "Copy the code",
        description: "Click the Copy button below to copy the tracking snippet.",
      },
      {
        title: "Add to your website",
        description:
          "Paste the snippet in your website's HTML, inside the <head> tag (before </head>).",
      },
    ],
    note: "Most website builders have a 'Custom Code' or 'Header Scripts' section in settings where you can paste this.",
  },
};

export function getGuide(platform: string): PlatformGuide {
  return platformGuides[platform] || platformGuides.unknown;
}
