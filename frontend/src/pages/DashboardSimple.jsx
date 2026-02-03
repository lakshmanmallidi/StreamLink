import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import iconImage from "../../icon.png";
import { apiFetch } from "../apiClient";

export default function Dashboard({ children }) {
  const [user, setUser] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [clusters, setClusters] = useState([]);
  const [services, setServices] = useState([]);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const userJson = localStorage.getItem("user");
    if (userJson) {
      setUser(JSON.parse(userJson));
      fetchClusters();
      fetchServices();
    } else {
      window.location.href = "/login";
    }
  }, []);

  const checkClusterStatus = async (clusterId) => {
    try {
      await apiFetch(`/v1/clusters/${clusterId}/check-status`, { method: "POST" });
    } catch (err) {
      console.error("Error checking cluster status:", err);
    }
  };

  const fetchClusters = async () => {
    try {
      const response = await apiFetch(`/v1/clusters`);
      const data = await response.json();
      setClusters(data);
    } catch (err) {
      console.error("Error fetching clusters:", err);
    }
  };

  const fetchServices = async () => {
    try {
      const response = await apiFetch(`/v1/services`);
      const data = await response.json();
      setServices(data);
    } catch (err) {
      console.error("Error fetching services:", err);
    }
  };

  const handleLogout = async () => {
    try {
      const idToken = localStorage.getItem("id_token");
      const accessToken = localStorage.getItem("access_token");
      
      // Build logout URL with id_token_hint if available
      let logoutUrl = `${API_BASE_URL}/v1/auth/logout-url`;
      if (idToken) {
        logoutUrl += `?id_token_hint=${idToken}`;
      }
      
      // Get Keycloak logout URL (requires authentication)
      const response = await fetch(logoutUrl, {
        headers: { Authorization: `Bearer ${accessToken}` }
      });
      const data = await response.json();
      
      // Clear local storage AFTER getting logout URL
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      localStorage.removeItem("id_token");
      sessionStorage.removeItem("pkce_code_verifier");
      
      // If Keycloak logout URL exists, redirect to it
      if (data.logout_url) {
        window.location.href = data.logout_url;
      } else {
        // Fallback to local login page
        window.location.href = "/login";
      }
    } catch (err) {
      console.error("Logout error:", err);
      // Fallback: clear tokens and go to login
      localStorage.removeItem("access_token");
      localStorage.removeItem("user");
      localStorage.removeItem("id_token");
      sessionStorage.removeItem("pkce_code_verifier");
      window.location.href = "/login";
    }
  };

  if (!user) return <div>Loading...</div>;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* Sidebar */}
      <div
        style={{
          width: sidebarOpen ? "260px" : "0",
          backgroundColor: "white",
          color: "#1e3a8a",
          transition: "width 0.3s ease",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid #e5e7eb",
          boxShadow: "2px 0 5px rgba(0,0,0,0.05)"
        }}
      >
        {/* Sidebar Header */}
        <div style={{ padding: "20px", borderBottom: "1px solid #e5e7eb", display: "flex", alignItems: "center", gap: "12px" }}>
          <img src={iconImage} alt="StreamLink" style={{ width: "28px", height: "28px" }} />
          <h2 style={{ margin: 0, fontSize: "20px", fontWeight: "600", color: "#1e3a8a" }}>
            StreamLink
          </h2>
        </div>

        {/* Sidebar Menu */}
        <div style={{ flex: 1, padding: "20px 0" }}>
          <div
            onClick={() => navigate("/")}
            style={{
              padding: "12px 20px",
              cursor: "pointer",
              backgroundColor: location.pathname === "/" ? "#eff6ff" : "transparent",
              borderLeft: location.pathname === "/" ? "4px solid #2563eb" : "4px solid transparent",
              color: "#1e3a8a",
              fontWeight: "500",
            }}
          >
            Dashboard
          </div>
          <div
            onClick={() => navigate("/clusters")}
            style={{
              padding: "12px 20px",
              cursor: "pointer",
              backgroundColor: location.pathname.startsWith("/clusters") ? "#eff6ff" : "transparent",
              borderLeft: location.pathname.startsWith("/clusters") ? "4px solid #2563eb" : "4px solid transparent",
              color: "#1e3a8a",
              fontWeight: "500",
            }}
          >
            Kubernetes
          </div>
          <div
            onClick={() => navigate("/services")}
            style={{
              padding: "12px 20px",
              cursor: "pointer",
              backgroundColor: location.pathname.startsWith("/services") ? "#eff6ff" : "transparent",
              borderLeft: location.pathname.startsWith("/services") ? "4px solid #2563eb" : "4px solid transparent",
              color: "#1e3a8a",
              fontWeight: "500",
            }}
          >
            Services
          </div>
        </div>

        {/* User Info at Bottom */}
        <div
          style={{
            borderTop: "1px solid #e5e7eb",
            padding: "20px",
            backgroundColor: "#f9fafb"
          }}
        >
          <div style={{ marginBottom: "15px" }}>
            <div style={{ fontSize: "12px", color: "#6b7280", marginBottom: "4px" }}>
              Logged in as
            </div>
            <div style={{ fontSize: "14px", fontWeight: "500", color: "#1e3a8a" }}>
              {user.username}
            </div>
            {user.email && (
              <div style={{ fontSize: "12px", color: "#6b7280", marginTop: "2px" }}>
                {user.email}
              </div>
            )}
          </div>
          <button
            onClick={handleLogout}
            style={{
              width: "100%",
              padding: "10px",
              backgroundColor: "white",
              color: "#1e3a8a",
              border: "1px solid #d1d5db",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "14px",
              fontWeight: "500"
            }}
          >
            Logout
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {/* Top Bar */}
        <div
          style={{
            height: "60px",
            backgroundColor: "white",
            borderBottom: "1px solid #e5e7eb",
            display: "flex",
            alignItems: "center",
            padding: "0 20px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.1)"
          }}
        >
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            style={{
              backgroundColor: "transparent",
              border: "none",
              cursor: "pointer",
              padding: "8px",
              display: "flex",
              flexDirection: "column",
              gap: "4px"
            }}
          >
            <div style={{ width: "24px", height: "3px", backgroundColor: "#1e3a8a" }}></div>
            <div style={{ width: "24px", height: "3px", backgroundColor: "#1e3a8a" }}></div>
            <div style={{ width: "24px", height: "3px", backgroundColor: "#1e3a8a" }}></div>
          </button>
        </div>

        {/* Content Area */}
        <div
          style={{
            flex: 1,
            backgroundColor: "#f3f4f6",
            padding: "30px",
            overflow: "auto"
          }}
        >
          {children || (
            <div
              style={{
                backgroundColor: "white",
                borderRadius: "8px",
                padding: "30px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.1)"
              }}
            >
              {clusters.length > 0 && (
                  <>
                    <h3 style={{ margin: "30px 0 15px 0", color: "#1e3a8a" }}>
                      Kubernetes Cluster
                    </h3>
                    <div
                      style={{
                        backgroundColor: "#f9fafb",
                        border: "1px solid #e5e7eb",
                        borderRadius: "6px",
                        padding: "20px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <strong style={{ color: "#1e3a8a", fontSize: "16px" }}>{clusters[0].name}</strong>
                          <p style={{ margin: "5px 0 0 0", fontSize: "13px", color: "#6b7280" }}>
                            {clusters[0].api_server}
                          </p>
                        </div>
                        <span
                          style={{
                            padding: "6px 14px",
                            backgroundColor:
                              clusters[0].status === "up"
                                ? "#d1fae5"
                                : clusters[0].status === "down"
                                ? "#fee2e2"
                                : "#f3f4f6",
                            color:
                              clusters[0].status === "up"
                                ? "#065f46"
                                : clusters[0].status === "down"
                                ? "#991b1b"
                                : "#6b7280",
                            borderRadius: "12px",
                            fontSize: "12px",
                            fontWeight: "500",
                          }}
                        >
                          {clusters[0].status === "up" ? "🟢 Connected" : clusters[0].status === "down" ? "🔴 Disconnected" : "⚪ Unknown"}
                        </span>
                      </div>
                      <button
                        onClick={() => navigate("/clusters")}
                        style={{
                          marginTop: "15px",
                          padding: "8px 16px",
                          backgroundColor: "white",
                          color: "#2563eb",
                          border: "1px solid #2563eb",
                          borderRadius: "4px",
                          cursor: "pointer",
                          fontSize: "13px",
                        }}
                      >
                        Manage Cluster
                      </button>
                    </div>
                  </>
                )}

              {services.length > 0 && (
                <>
                  <h3 style={{ margin: "30px 0 15px 0", color: "#1e3a8a" }}>
                    Deployed Services
                  </h3>
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                    {services.map((service) => (
                      <div
                        key={service.id}
                        style={{
                          backgroundColor: "#f9fafb",
                          border: "1px solid #e5e7eb",
                          borderRadius: "6px",
                          padding: "15px",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                        }}
                      >
                        <div>
                          <strong style={{ color: "#1e3a8a", fontSize: "14px" }}>{service.display_name}</strong>
                          <p style={{ margin: "5px 0 0 0", fontSize: "12px", color: "#6b7280" }}>
                            {service.namespace} {service.replicas && `• ${service.replicas} replicas`}
                          </p>
                        </div>
                        <span
                          style={{
                            padding: "4px 12px",
                            backgroundColor:
                              service.status === "running"
                                ? "#d1fae5"
                                : service.status === "deploying"
                                ? "#fef3c7"
                                : service.status === "pending"
                                ? "#e0e7ff"
                                : service.status === "failed"
                                ? "#fee2e2"
                                : "#f3f4f6",
                            color:
                              service.status === "running"
                                ? "#065f46"
                                : service.status === "deploying"
                                ? "#92400e"
                                : service.status === "pending"
                                ? "#3730a3"
                                : service.status === "failed"
                                ? "#991b1b"
                                : "#6b7280",
                            borderRadius: "12px",
                            fontSize: "11px",
                            fontWeight: "500",
                          }}
                        >
                          {service.status === "running" ? "🟢" : service.status === "deploying" ? "🟡" : service.status === "pending" ? "🔵" : service.status === "failed" ? "🔴" : "⚪"} {service.status}
                        </span>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => navigate("/services")}
                    style={{
                      marginTop: "15px",
                      padding: "8px 16px",
                      backgroundColor: "white",
                      color: "#2563eb",
                      border: "1px solid #2563eb",
                      borderRadius: "4px",
                      cursor: "pointer",
                      fontSize: "13px",
                    }}
                  >
                    Manage Services
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
