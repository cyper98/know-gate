/** /admin/sources — list, sync-now, delete. Admin only. */
import { requireRole } from "@/lib/auth";
import { AdminSourcesTable } from "./sources-table";

export const dynamic = "force-dynamic";

export default async function AdminSourcesPage() {
  await requireRole(["admin"]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Sources</h1>
      <AdminSourcesTable />
    </div>
  );
}
