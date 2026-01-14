import type { ReactNode } from "react";

export const metadata = {
  title: "TNChatbot",
  description: "TNChatbot frontend",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>{children}</body>
    </html>
  );
}
