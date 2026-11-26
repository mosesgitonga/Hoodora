import {
  AuditOutlined,
  DashboardOutlined,
  FlagOutlined,
  GlobalOutlined,
  SettingOutlined,
  StopOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { ThemedLayout, ThemedTitle, useNotificationProvider } from "@refinedev/antd";
import { Authenticated, CanAccess, Refine, type NotificationProvider } from "@refinedev/core";
import routerProvider, { CatchAllNavigate } from "@refinedev/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { App as AntdApp, ConfigProvider, Result } from "antd";
import enGB from "antd/locale/en_GB";
import { useEffect, type ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useNavigate } from "react-router";

import { onSessionEnded } from "./api";
import { cspNonce } from "./config";
import { Account } from "./pages/Account";
import { Audit } from "./pages/Audit";
import { Bans } from "./pages/Bans";
import { Content } from "./pages/Content";
import { GodsView } from "./pages/GodsView";
import { Overview } from "./pages/Overview";
import { People } from "./pages/People";
import { Person } from "./pages/Person";
import { Queue } from "./pages/Queue";
import { SignIn } from "./pages/SignIn";
import { StaffPage } from "./pages/Staff";
import { accessControlProvider, authProvider, dataProvider } from "./providers";
import { currentStaff } from "./session";
import { THEME } from "./theme";

const resources = [
  { name: "overview", list: "/overview", meta: { label: "Overview", icon: <DashboardOutlined /> } },
  { name: "map", list: "/map", meta: { label: "God's view", icon: <GlobalOutlined /> } },
  { name: "queue", list: "/queue", show: "/queue/:type/:id", meta: { label: "Reports", icon: <FlagOutlined /> } },
  { name: "people", list: "/people", show: "/people/:id", meta: { label: "People", icon: <UserOutlined /> } },
  { name: "bans", list: "/bans", meta: { label: "Ban lists", icon: <StopOutlined /> } },
  { name: "audit", list: "/audit", meta: { label: "Audit log", icon: <AuditOutlined /> } },
  { name: "staff", list: "/staff", meta: { label: "Staff", icon: <TeamOutlined /> } },
  { name: "account", list: "/account", meta: { label: "My account", icon: <SettingOutlined /> } },
];

/** Where someone lands: the overview for admins, the queue for moderators. */
function Home() {
  return <Navigate to={currentStaff()?.role === "admin" ? "/overview" : "/queue"} replace />;
}

function Guard({ resource, children }: { resource: string; children: ReactNode }) {
  return (
    <CanAccess
      resource={resource}
      action="list"
      fallback={<Result status="403" title="That needs an admin" subTitle="Ask an admin if you need this." />}
    >
      {children}
    </CanAccess>
  );
}

/** When the session ends (signed out, idle, or a 401), forget everything the
 * screens loaded and go back to signing in. */
function SessionWatcher() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useEffect(
    () =>
      onSessionEnded(() => {
        queryClient.clear();
        navigate("/sign-in", { replace: true });
      }),
    [navigate, queryClient],
  );
  return null;
}

/** Refine's notifications, less its error toasts. Every screen shows a failure
 * where it happened (a load in place of the content, an action in its dialog,
 * signing in on the form, the same message every time), so a toast as well
 * would only say it twice. */
function useNotifications(): NotificationProvider {
  const provider = useNotificationProvider();
  return {
    ...provider,
    open: (params) => {
      if (params.type !== "error") provider.open(params);
    },
  };
}

function Title({ collapsed }: { collapsed: boolean }) {
  return <ThemedTitle collapsed={collapsed} text="Hoodora admin" icon={<img src="/favicon.svg" alt="" width={24} height={24} />} />;
}

function Shell() {
  return (
    <Refine
      routerProvider={routerProvider}
      dataProvider={dataProvider}
      authProvider={authProvider}
      accessControlProvider={accessControlProvider}
      notificationProvider={useNotifications}
      resources={resources}
      options={{
        // No analytics, anywhere (the brief); the CSP would block it anyway.
        disableTelemetry: true,
        syncWithLocation: false,
        warnWhenUnsavedChanges: false,
        reactQuery: { clientConfig: { defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } } },
      }}
    >
      <SessionWatcher />
      <Routes>
        <Route
          element={
            <Authenticated key="app" fallback={<CatchAllNavigate to="/sign-in" />}>
              <ThemedLayout Title={Title}>
                <Outlet />
              </ThemedLayout>
            </Authenticated>
          }
        >
          <Route index element={<Home />} />
          <Route path="/overview" element={<Guard resource="overview"><Overview /></Guard>} />
          <Route path="/map" element={<Guard resource="map"><GodsView /></Guard>} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/queue/:type/:id" element={<Content />} />
          <Route path="/people" element={<People />} />
          <Route path="/people/:id" element={<Person />} />
          <Route path="/bans" element={<Guard resource="bans"><Bans /></Guard>} />
          <Route path="/audit" element={<Guard resource="audit"><Audit /></Guard>} />
          <Route path="/staff" element={<Guard resource="staff"><StaffPage /></Guard>} />
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<Result status="404" title="Nothing here" subTitle="That page doesn't exist." />} />
        </Route>
        <Route
          element={
            <Authenticated key="auth" fallback={<Outlet />}>
              <Home />
            </Authenticated>
          }
        >
          <Route path="/sign-in" element={<SignIn />} />
        </Route>
      </Routes>
    </Refine>
  );
}

export function App() {
  return (
    <ConfigProvider theme={THEME} locale={enGB} csp={{ nonce: cspNonce() }}>
      <AntdApp>
        <Shell />
      </AntdApp>
    </ConfigProvider>
  );
}
