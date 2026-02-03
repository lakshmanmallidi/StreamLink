import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../apiClient";

export default function AddCluster() {
  const [formData, setFormData] = useState({
    name: "",
    api_server: "",
    kubeconfig: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await apiFetch(`/v1/clusters`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to add cluster");
      }

      navigate("/clusters");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 style={{ margin: "0 0 20px 0", color: "#1e3a8a" }}>Add Kubernetes Cluster</h2>

      <div
        style={{
          backgroundColor: "white",
          borderRadius: "8px",
          padding: "30px",
          maxWidth: "600px",
        }}
      >
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "20px" }}>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                color: "#374151",
                fontSize: "14px",
                fontWeight: "500",
              }}
            >
              Cluster Name *
            </label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., production-cluster"
              style={{
                width: "100%",
                padding: "10px",
                border: "1px solid #d1d5db",
                borderRadius: "4px",
                fontSize: "14px",
              }}
            />
          </div>

          <div style={{ marginBottom: "20px" }}>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                color: "#374151",
                fontSize: "14px",
                fontWeight: "500",
              }}
            >
              API Server URL *
            </label>
            <input
              type="text"
              required
              value={formData.api_server}
              onChange={(e) => setFormData({ ...formData, api_server: e.target.value })}
              placeholder="e.g., https://kubernetes.example.com:6443"
              style={{
                width: "100%",
                padding: "10px",
                border: "1px solid #d1d5db",
                borderRadius: "4px",
                fontSize: "14px",
              }}
            />
          </div>

          <div style={{ marginBottom: "20px" }}>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                color: "#374151",
                fontSize: "14px",
                fontWeight: "500",
              }}
            >
              Kubeconfig *
            </label>
            <textarea
              required
              value={formData.kubeconfig}
              onChange={(e) => setFormData({ ...formData, kubeconfig: e.target.value })}
              placeholder="Paste your kubeconfig content here..."
              rows="10"
              style={{
                width: "100%",
                padding: "10px",
                border: "1px solid #d1d5db",
                borderRadius: "4px",
                fontSize: "13px",
                fontFamily: "monospace",
                resize: "vertical",
              }}
            />
            <p style={{ margin: "6px 0 0 0", fontSize: "12px", color: "#6b7280" }}>
              Get this from: kubectl config view --raw --minify
            </p>
          </div>

          {error && (
            <div
              style={{
                padding: "12px",
                backgroundColor: "#fee2e2",
                border: "1px solid #fecaca",
                borderRadius: "4px",
                color: "#991b1b",
                fontSize: "14px",
                marginBottom: "20px",
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="submit"
              disabled={loading}
              style={{
                padding: "10px 20px",
                backgroundColor: loading ? "#9ca3af" : "#2563eb",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: loading ? "not-allowed" : "pointer",
                fontSize: "14px",
                fontWeight: "500",
              }}
            >
              {loading ? "Adding..." : "Add Cluster"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/clusters")}
              style={{
                padding: "10px 20px",
                backgroundColor: "white",
                color: "#6b7280",
                border: "1px solid #d1d5db",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
