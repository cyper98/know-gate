/** /admin/audit-log — admin only. */
import { requireRole } from "@/lib/auth";
import { AdminAuditList } from "./audit-list";

export const dynamic = "force-dynamic";

export default async function AdminAuditLogPage() {
  await requireRole(["admin"]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Audit log</h1>
      <AdminAuditList />
    </div>
  );
}
