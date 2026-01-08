import { useRoutes, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import DashboardSimple from "./pages/DashboardSimple";
import LoginSimple from "./pages/LoginSimple";
import AuthCallbackSimple from "./pages/AuthCallbackSimple";
import Clusters from "./pages/Clusters";
import AddCluster from "./pages/AddCluster";
import Services from "./pages/Services";
import NotFound from "./pages/NotFound";
import "./App.css";

function ProtectedRoute({ element }) {
  const [isAuthenticated, setIsAuthenticated] = useState(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    const hasToken = !!token;
    setIsAuthenticated(hasToken);
  }, []);

  if (isAuthenticated === null) {
    return <div>Loading...</div>;
  }

  return isAuthenticated ? element : <Navigate to="/login" />;
}

const routes = [
  {
    path: "/",
    element: <ProtectedRoute element={<DashboardSimple />} />,
  },
  {
    path: "/clusters",
    element: <ProtectedRoute element={<DashboardSimple><Clusters /></DashboardSimple>} />,
  },
  {
    path: "/clusters/add",
    element: <ProtectedRoute element={<DashboardSimple><AddCluster /></DashboardSimple>} />,
  },
  {
    path: "/services",
    element: <ProtectedRoute element={<DashboardSimple><Services /></DashboardSimple>} />,
  },
  {
    path: "/login",
    element: <LoginSimple />,
  },
  {
    path: "/auth/callback",
    element: <AuthCallbackSimple />,
  },
  {
    path: "*",
    element: <NotFound />,
  },
];

function App() {
  const element = useRoutes(routes);
  return element;
}

export default App;
