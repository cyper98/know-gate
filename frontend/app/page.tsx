/** Root entry — bounce signed-in users to /dashboard, others to /login. */
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";

export default function HomePage() {
  const user = getCurrentUser();
  redirect(user ? "/dashboard" : "/login");
}
