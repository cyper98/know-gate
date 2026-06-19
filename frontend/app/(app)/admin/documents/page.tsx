/** /admin/documents — document management page (admin only). */
import { requireAuth } from "@/lib/auth";
import { AdminDocumentsTable } from "./documents-table";

export const dynamic = "force-dynamic";

export default async function AdminDocumentsPage() {
  await requireAuth();
  return <AdminDocumentsTable />;
}
