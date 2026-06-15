/** /login — entry point for password / OAuth / magic-link sign-in. */
import { Suspense } from "react";

import { LoginForm } from "./login-form";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
