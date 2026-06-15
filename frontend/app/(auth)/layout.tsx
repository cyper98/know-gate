/** Layout for the (auth) route group — minimal centered container. */
import { LangSwitcher } from "@/components/lang-switcher";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <div className="ml-auto p-4">
        <LangSwitcher />
      </div>
      <div className="flex flex-1 items-center justify-center p-4">{children}</div>
    </div>
  );
}
