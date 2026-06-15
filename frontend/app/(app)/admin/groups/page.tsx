/** /admin/groups — list + delete. Admin only. */
import { requireRole } from "@/lib/auth";
import { AdminGroupsTable } from "./groups-table";

export const dynamic = "force-dynamic";

export default async function AdminGroupsPage() {
  await requireRole(["admin"]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Groups</h1>
      <AdminGroupsTable />
    </div>
  );
}
