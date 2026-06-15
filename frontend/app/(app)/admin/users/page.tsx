/** /admin/users — invite, list, soft-delete. Admin only. */
import { requireRole } from "@/lib/auth";
import { AdminUsersTable } from "./users-table";

export const dynamic = "force-dynamic";

export default async function AdminUsersPage() {
  await requireRole(["admin"]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Users</h1>
      <AdminUsersTable />
    </div>
  );
}
