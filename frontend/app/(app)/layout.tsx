/** (app) layout — auth-gated. Reads the user from cookies and feeds it to
 *  the AppShell (client component) via the UserProvider context. */
import { getCurrentUser } from "@/lib/auth";
import { AppShell } from "@/components/app-shell";
import { UserProvider } from "@/components/user-provider";

export const dynamic = "force-dynamic";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const user = getCurrentUser();
  return (
    <UserProvider user={user}>
      <AppShell>{children}</AppShell>
    </UserProvider>
  );
}
