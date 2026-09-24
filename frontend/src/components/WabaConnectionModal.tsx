import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { WabaConnectionStatus, WabaConnectionWrite } from "../api/types";

type Props = {
  organizationId: string;
  organizationName: string;
  onClose: () => void;
};

const emptyForm: WabaConnectionWrite = {
  business_id: "",
  waba_id: "",
  phone_number_id: "",
  channel_account_id: "",
  api_version: "v23.0",
  access_token: ""
};

export function WabaConnectionModal({ organizationId, organizationName, onClose }: Props) {
  const client = useQueryClient();
  const [form, setForm] = useState<WabaConnectionWrite>(emptyForm);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ status: WabaConnectionStatus; testedAt: string } | null>(null);
  const seededForOrg = useRef<string | null>(null);

  const connectionQuery = useQuery({
    queryKey: ["waba-connection", organizationId],
    queryFn: () => api.getWabaConnection(organizationId)
  });

  // Seed the form from the server once per organization — a later refetch
  // (e.g. after "Testar conexão") must not clobber edits the user hasn't saved yet.
  useEffect(() => {
    if (!connectionQuery.data || seededForOrg.current === organizationId) return;
    const connection = connectionQuery.data;
    seededForOrg.current = organizationId;
    setTestResult(null);
    setForm({
      business_id: connection.business_id ?? "",
      waba_id: connection.waba_id ?? "",
      phone_number_id: connection.phone_number_id ?? "",
      channel_account_id: connection.channel_account_id ?? "",
      api_version: connection.api_version,
      access_token: ""
    });
  }, [connectionQuery.data, organizationId]);

  const saveMutation = useMutation({
    mutationFn: () => api.updateWabaConnection(organizationId, form),
    onSuccess: async (connection) => {
      seededForOrg.current = organizationId;
      setForm({
        business_id: connection.business_id ?? "",
        waba_id: connection.waba_id ?? "",
        phone_number_id: connection.phone_number_id ?? "",
        channel_account_id: connection.channel_account_id ?? "",
        api_version: connection.api_version,
        access_token: ""
      });
      await client.invalidateQueries({ queryKey: ["waba-connection", organizationId] });
      setNotice("Conexão salva.");
    },
    onError: (error: Error) => setNotice(error.message)
  });

  const testMutation = useMutation({
    mutationFn: () => api.testWabaConnection(organizationId),
    onSuccess: (result) => {
      setTestResult({ status: result.status, testedAt: new Date().toISOString() });
      setNotice(result.detail);
    },
    onError: (error: Error) => setNotice(error.message)
  });

  const connection = connectionQuery.data;
  const displayStatus = testResult?.status ?? connection?.status;
  const displayTestedAt = testResult?.testedAt ?? connection?.last_synced_at;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal connection-modal" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <div className="modal-title">
          <span className="category utility">CONEXÃO WABA</span>
          <h2>{organizationName}</h2>
          <p>Dados da WhatsApp Business Account e do número usado para enviar templates desta empresa.</p>
        </div>
        <div className="connection-form">
          {displayStatus && (
            <div className={`connection-status ${displayStatus.toLowerCase()}`}>
              <span className="dot" /> {displayStatus === "CONNECTED" ? "Conectado" : displayStatus === "ERROR" ? "Erro na última verificação" : "Desconectado"}
              {displayTestedAt && <small> · testado em {new Date(displayTestedAt).toLocaleString("pt-BR")}</small>}
            </div>
          )}
          <label>Business ID
            <input value={form.business_id ?? ""} onChange={(event) => setForm({ ...form, business_id: event.target.value })} placeholder="Ex.: 123456789012345" />
          </label>
          <label>WABA ID
            <input value={form.waba_id ?? ""} onChange={(event) => setForm({ ...form, waba_id: event.target.value })} placeholder="Ex.: 987654321098765" />
          </label>
          <label>Phone Number ID
            <input value={form.phone_number_id ?? ""} onChange={(event) => setForm({ ...form, phone_number_id: event.target.value })} placeholder="Ex.: 111222333444555" />
          </label>
          <label>Channel Account ID (middleware)
            <input value={form.channel_account_id ?? ""} onChange={(event) => setForm({ ...form, channel_account_id: event.target.value })} placeholder="UUID da conta de canal" />
          </label>
          <label>Versão da Graph API
            <input value={form.api_version} onChange={(event) => setForm({ ...form, api_version: event.target.value })} placeholder="v23.0" />
          </label>
          <label>Token de acesso
            <input
              type="password"
              value={form.access_token ?? ""}
              onChange={(event) => setForm({ ...form, access_token: event.target.value })}
              placeholder={connection?.has_token ? "•••••••••••••• (deixe em branco para manter)" : "Cole o token do system user"}
            />
            <span className="field-hint">Cifrado no banco com a chave da aplicação. Em produção, prefira KMS ou secret manager.</span>
          </label>
        </div>
        <footer>
          <span className="muted">{notice ?? " "}</span>
          <div>
            <button className="ghost" disabled={testMutation.isPending} onClick={() => testMutation.mutate()}>{testMutation.isPending ? "Testando…" : "Testar conexão"}</button>
            <button className="primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? "Salvando…" : "Salvar"}</button>
          </div>
        </footer>
      </div>
    </div>
  );
}
