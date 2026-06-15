/** /admin/settings — read-only system settings. Admin only. */
import { requireRole } from "@/lib/auth";
import { AdminSettingsView } from "./settings-view";

export const dynamic = "force-dynamic";

export default async function AdminSettingsPage() {
  await requireRole(["admin"]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <AdminSettingsView />
    </div>
  );
}
