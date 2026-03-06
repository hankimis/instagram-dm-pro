export default function Footer() {
  return (
    <footer className="px-6 py-10 text-center" style={{ borderTop: "1px solid var(--gray-200)" }}>
      <p className="text-sm" style={{ color: "var(--gray-500)" }}>
        &copy; {new Date().getFullYear()} Instagram DM Pro. All rights reserved.
      </p>
    </footer>
  );
}
