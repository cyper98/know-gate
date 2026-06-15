/** /query/history — paginated past questions + detail. */
import { Suspense } from "react";

import { HistoryList } from "./history-list";

export const dynamic = "force-dynamic";

export default function HistoryPage() {
  return (
    <Suspense fallback={null}>
      <HistoryList />
    </Suspense>
  );
}
