import "./globals.css";

export const metadata = { title: "AI Agent Arena", description: "Race AI coding agents, bet on the winner." };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <a href="/" className="logo">⚔ AI Agent Arena</a>
          <span className="muted">play money only · devnet</span>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
