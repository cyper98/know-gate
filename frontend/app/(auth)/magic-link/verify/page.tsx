/** /magic-link/verify — entry point that consumes the ?token= in the URL. */
import { Suspense } from "react";

import { MagicLinkVerify } from "./magic-verify";

export const dynamic = "force-dynamic";

export default function MagicLinkVerifyPage() {
  return (
    <Suspense fallback={null}>
      <MagicLinkVerify />
    </Suspense>
  );
}
