/** /dashboard — landing page for signed-in users. */
import { requireAuth } from "@/lib/auth";
import { DashboardWidgets } from "./dashboard-widgets";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const user = await requireAuth();
  return <DashboardWidgets userId={user.id} displayName={user.display_name} />;
}
