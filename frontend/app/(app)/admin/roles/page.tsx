/** /admin/roles — list + delete. Admin only. */
import { requireRole } from "@/lib/auth";
import { AdminRolesTable } from "./roles-table";

export const dynamic = "force-dynamic";

export default async function AdminRolesPage() {
  await requireRole(["admin"]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Roles</h1>
      <AdminRolesTable />
    </div>
  );
}
