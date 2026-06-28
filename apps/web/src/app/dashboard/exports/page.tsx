import { redirect } from "next/navigation";

// The Exports tab was folded into the unified Connectors tab. Keep this route as
// a permanent redirect so old bookmarks and in-app links still land correctly.
export default function ExportsRedirect() {
  redirect("/dashboard/connectors");
}
