import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from "react";

import { api } from "../api/client";
import type { Organization } from "../api/types";

const STORAGE_KEY = "evig.current-organization-id";

type OrganizationContextValue = {
  organizationId: string | null;
  organizations: Organization[];
  isLoading: boolean;
  setOrganizationId: (id: string) => void;
  refreshOrganizations: () => Promise<void>;
};

const OrganizationContext = createContext<OrganizationContextValue | null>(null);

function readStoredId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredId(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // localStorage indisponível (modo privado, etc.) — segue só em memória.
  }
}

export function OrganizationProvider({ children }: PropsWithChildren) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["organizations"], queryFn: api.listOrganizations });
  const [organizationId, setOrganizationIdState] = useState<string | null>(readStoredId);

  useEffect(() => {
    if (!query.data || query.data.length === 0) return;
    const stillExists = organizationId && query.data.some((org) => org.id === organizationId);
    if (!stillExists) {
      setOrganizationIdState(query.data[0].id);
      writeStoredId(query.data[0].id);
    }
  }, [query.data, organizationId]);

  const value = useMemo<OrganizationContextValue>(
    () => ({
      organizationId,
      organizations: query.data ?? [],
      isLoading: query.isLoading,
      setOrganizationId: (id: string) => {
        setOrganizationIdState(id);
        writeStoredId(id);
      },
      refreshOrganizations: async () => {
        await client.invalidateQueries({ queryKey: ["organizations"] });
      }
    }),
    [organizationId, query.data, query.isLoading, client]
  );

  return <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>;
}

export function useOrganization(): OrganizationContextValue {
  const context = useContext(OrganizationContext);
  if (!context) throw new Error("useOrganization deve ser usado dentro de OrganizationProvider");
  return context;
}
