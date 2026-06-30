import { Receipt, BookOpen, ListChecks, Inbox, Sparkles } from "lucide-react";
import type { ComponentType } from "react";

export type AdminTool = {
  href: string;
  label: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
};

/** Admin-only tools, surfaced together on the /dashboard/admin hub page and as
 *  a single "Admin" entry in the sidebar. Pages themselves live at their own
 *  routes and are backend-gated to admins. */
export const ADMIN_TOOLS: AdminTool[] = [
  {
    href: "/dashboard/costs",
    label: "API Costs",
    description: "External API spend across providers.",
    icon: Receipt,
  },
  {
    href: "/dashboard/blog",
    label: "Blog",
    description: "Write and publish blog posts.",
    icon: BookOpen,
  },
  {
    href: "/dashboard/changelog",
    label: "Changelog",
    description: "Post product updates to the landing page.",
    icon: Sparkles,
  },
  {
    href: "/dashboard/waitlist",
    label: "Waitlist",
    description: "Review and manage signups.",
    icon: ListChecks,
  },
  {
    href: "/dashboard/feature-requests",
    label: "Feature Requests",
    description: "Incoming user feature requests.",
    icon: Inbox,
  },
];
