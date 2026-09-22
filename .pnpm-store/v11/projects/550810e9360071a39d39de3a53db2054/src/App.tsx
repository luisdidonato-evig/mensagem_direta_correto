import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { DirectMessagesPage } from "./pages/DirectMessagesPage";
import { ResultsPage } from "./pages/ResultsPage";
import { AccessPage } from "./pages/AccessPage";
import { getAccessToken } from "./api/client";

export default function App() {
  if (import.meta.env.VITE_AUTH_ENABLED === "true" && !getAccessToken()) {
    return <AccessPage />;
  }
  return <Layout><Routes><Route path="/mensagem-direta" element={<DirectMessagesPage />} /><Route path="/resultados" element={<ResultsPage />} /><Route path="*" element={<Navigate to="/mensagem-direta" replace />} /></Routes></Layout>;
}
