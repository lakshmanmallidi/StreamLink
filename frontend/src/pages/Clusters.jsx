import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../apiClient";

export default function Clusters() {
  const [cluster, setCluster] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    fetchCluster();
  }, []);

  // Auto-check cluster status every 5 seconds
  useEffect(() => {
    if (!cluster) return;

    const interval = setInterval(() => {
      checkStatus();
    }, 5000);

    return () => clearInterval(interval);
  }, [cluster]);

  const fetchCluster = async () => {
    try {
      const response = await apiFetch(`/v1/clusters`);
      const data = await response.json();
      setCluster(data.length > 0 ? data[0] : null);
    } catch (err) {
      console.error("Error fetching cluster:", err);
    } finally {
      setLoading(false);
    }
  };

  const checkStatus = async () => {
    try {
      await apiFetch(`/v1/clusters/${cluster.id}/check-status`, { method: "POST" });
      fetchCluster();
    } catch (err) {
      console.error("Error checking status:", err);
    }
  };

  const deleteCluster = async () => {
    if (!confirm("Are you sure you want to delete this cluster configuration?")) return;
    
    try {
      await apiFetch(`/v1/clusters/${cluster.id}`, { method: "DELETE" });
      fetchCluster();
    } catch (err) {
      console.error("Error deleting cluster:", err);
    }
  };

  if (loading) return <div style={{ padding: "30px" }}>Loading...</div>;

  return (
    <div>
      <h2 style={{ margin: "0 0 20px 0", color: "#1e3a8a" }}>Kubernetes Cluster</h2>

      {!cluster ? (
        <div
          style={{
            textAlign: "center",
            padding: "60px 20px",
            backgroundColor: "#f9fafb",
            borderRadius: "8px",
            border: "1px dashed #d1d5db",
          }}
        >
          <p style={{ color: "#6b7280", marginBottom: "20px" }}>No cluster configured</p>
          <button
            onClick={() => navigate("/clusters/add")}
            style={{
              padding: "10px 20px",
              backgroundColor: "#2563eb",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            Configure Cluster
          </button>
        </div>
      ) : (
        <div
          style={{
            backgroundColor: "white",
            border: "1px solid #e5e7eb",
            borderRadius: "8px",
            padding: "30px",
          }}
        >
          <div style={{ marginBottom: "30px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "15px", marginBottom: "15px" }}>
              <h3 style={{ margin: 0, color: "#1e3a8a", fontSize: "20px" }}>{cluster.name}</h3>
              <span
                style={{
                  padding: "6px 16px",
                  backgroundColor: cluster.status === "up" ? "#d1fae5" : cluster.status === "down" ? "#fee2e2" : "#f3f4f6",
                  color: cluster.status === "up" ? "#065f46" : cluster.status === "down" ? "#991b1b" : "#6b7280",
                  borderRadius: "12px",
                  fontSize: "13px",
                  fontWeight: "500",
                }}
              >
                {cluster.status === "up" ? "🟢 Connected" : cluster.status === "down" ? "🔴 Disconnected" : "⚪ Unknown"}
              </span>
            </div>
            
            <div style={{ color: "#6b7280", fontSize: "14px" }}>
              <div style={{ marginBottom: "8px" }}>
                <strong style={{ color: "#374151" }}>API Server:</strong> {cluster.api_server}
              </div>
              {cluster.last_checked && (
                <div>
                  <strong style={{ color: "#374151" }}>Last Checked:</strong>{" "}
                  {new Date(cluster.last_checked).toLocaleString()}
                </div>
              )}
            </div>
          </div>

          <div style={{ display: "flex", gap: "10px", paddingTop: "20px", borderTop: "1px solid #e5e7eb" }}>
            <button
              onClick={() => navigate(`/clusters/edit/${cluster.id}`)}
              style={{
                padding: "10px 20px",
                backgroundColor: "#2563eb",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "14px",
                fontWeight: "500",
              }}
            >
              Edit Configuration
            </button>
            <button
              onClick={deleteCluster}
              style={{
                padding: "10px 20px",
                backgroundColor: "white",
                color: "#dc2626",
                border: "1px solid #fecaca",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "14px",
                fontWeight: "500",
              }}
            >
              Remove Cluster
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
