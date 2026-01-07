import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

export default function Services() {
  const [services, setServices] = useState([]);
  const [cluster, setCluster] = useState(null);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchCluster();
    fetchServices();
  }, []);

  // Auto-refresh service status every 5 seconds
  useEffect(() => {
    if (services.length === 0) return;

    const interval = setInterval(() => {
      // Check status for each service in Kubernetes
      services.forEach(service => checkServiceStatus(service.id));
    }, 5000);

    return () => clearInterval(interval);
  }, [services]);

  const checkServiceStatus = async (serviceId) => {
    try {
      const token = localStorage.getItem("access_token");
      await fetch(`http://localhost:3000/v1/services/${serviceId}/check-status`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      // Refresh the list after checking
      await fetchServices();
    } catch (err) {
      console.error("Error checking service status:", err);
    }
  };

  const fetchCluster = async () => {
    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch("http://localhost:3000/v1/clusters", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setCluster(data.length > 0 ? data[0] : null);
    } catch (err) {
      console.error("Error fetching cluster:", err);
    }
  };

  const fetchServices = async () => {
    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch("http://localhost:3000/v1/services", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setServices(data);
    } catch (err) {
      console.error("Error fetching services:", err);
    } finally {
      setLoading(false);
    }
  };

  const deployService = async (serviceName) => {
    if (!cluster) {
      alert("Please configure a Kubernetes cluster first");
      navigate("/clusters/add");
      return;
    }

    setDeploying(serviceName);
    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch("http://localhost:3000/v1/services", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          cluster_id: cluster.id,
          name: serviceName,
          namespace: "default",
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Deployment failed");
      }

      await fetchServices();
      alert(`${serviceName} deployed successfully!`);
    } catch (err) {
      console.error("Error deploying service:", err);
      alert(`Failed to deploy ${serviceName}: ${err.message}`);
    } finally {
      setDeploying(null);
    }
  };

  const deleteService = async (service) => {
    if (!confirm(`Are you sure you want to delete ${service.display_name}?`)) return;

    try {
      const token = localStorage.getItem("access_token");
      await fetch(`http://localhost:3000/v1/services/${service.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      await fetchServices();
    } catch (err) {
      console.error("Error deleting service:", err);
      alert("Failed to delete service");
    }
  };

  const availableServices = [
    {
      name: "schema-registry",
      displayName: "Schema Registry",
      description: "Confluent Schema Registry for managing Avro, JSON, and Protobuf schemas",
      icon: "📋",
    },
    {
      name: "kafka",
      displayName: "Apache Kafka",
      description: "Distributed event streaming platform (KRaft mode)",
      icon: "🔄",
    },
  ];

  const getStatusColor = (status) => {
    switch (status) {
      case "running":
        return { bg: "#d1fae5", color: "#065f46", icon: "🟢" };
      case "deploying":
        return { bg: "#fef3c7", color: "#92400e", icon: "🟡" };
      case "pending":
        return { bg: "#e0e7ff", color: "#3730a3", icon: "🔵" };
      case "failed":
        return { bg: "#fee2e2", color: "#991b1b", icon: "🔴" };
      case "degraded":
        return { bg: "#fed7aa", color: "#9a3412", icon: "🟠" };
      default:
        return { bg: "#f3f4f6", color: "#6b7280", icon: "⚪" };
    }
  };

  if (loading) return <div style={{ padding: "30px" }}>Loading...</div>;

  return (
    <div>
      <h2 style={{ margin: "0 0 10px 0", color: "#1e3a8a" }}>Services</h2>
      <p style={{ margin: "0 0 30px 0", color: "#6b7280", fontSize: "14px" }}>
        Deploy and manage services on your Kubernetes cluster
      </p>

      {!cluster && (
        <div
          style={{
            backgroundColor: "#fef3c7",
            border: "1px solid #fcd34d",
            borderRadius: "6px",
            padding: "15px",
            marginBottom: "30px",
            color: "#92400e",
          }}
        >
          ⚠️ No Kubernetes cluster configured.{" "}
          <button
            onClick={() => navigate("/clusters/add")}
            style={{
              background: "none",
              border: "none",
              color: "#2563eb",
              textDecoration: "underline",
              cursor: "pointer",
            }}
          >
            Configure one now
          </button>
        </div>
      )}

      {/* Deployed Services */}
      {services.length > 0 && (
        <div style={{ marginBottom: "40px" }}>
          <h3 style={{ margin: "0 0 15px 0", color: "#1e3a8a", fontSize: "16px" }}>
            Deployed Services
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {services.map((service) => {
              const statusStyle = getStatusColor(service.status);
              return (
                <div
                  key={service.id}
                  style={{
                    backgroundColor: "white",
                    border: "1px solid #e5e7eb",
                    borderRadius: "8px",
                    padding: "20px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
                      <strong style={{ color: "#1e3a8a", fontSize: "16px" }}>
                        {service.display_name}
                      </strong>
                      <span
                        style={{
                          padding: "4px 12px",
                          backgroundColor: statusStyle.bg,
                          color: statusStyle.color,
                          borderRadius: "12px",
                          fontSize: "12px",
                          fontWeight: "500",
                        }}
                      >
                        {statusStyle.icon} {service.status}
                      </span>
                    </div>
                    <div style={{ fontSize: "13px", color: "#6b7280" }}>
                      Namespace: {service.namespace}
                      {service.replicas && ` • Replicas: ${service.replicas}`}
                    </div>
                  </div>
                  <button
                    onClick={() => deleteService(service)}
                    style={{
                      padding: "8px 16px",
                      backgroundColor: "white",
                      color: "#dc2626",
                      border: "1px solid #fecaca",
                      borderRadius: "4px",
                      cursor: "pointer",
                      fontSize: "13px",
                    }}
                  >
                    Delete
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Available Services */}
      <div>
        <h3 style={{ margin: "0 0 15px 0", color: "#1e3a8a", fontSize: "16px" }}>
          Available Services
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "15px" }}>
          {availableServices.map((service) => {
            const isDeployed = services.some((s) => s.name === service.name);
            const isDeploying = deploying === service.name;

            return (
              <div
                key={service.name}
                style={{
                  backgroundColor: "white",
                  border: "1px solid #e5e7eb",
                  borderRadius: "8px",
                  padding: "20px",
                  opacity: service.disabled || isDeployed ? 0.6 : 1,
                }}
              >
                <div style={{ fontSize: "32px", marginBottom: "10px" }}>{service.icon}</div>
                <h4 style={{ margin: "0 0 8px 0", color: "#1e3a8a" }}>{service.displayName}</h4>
                <p style={{ margin: "0 0 15px 0", fontSize: "13px", color: "#6b7280", lineHeight: "1.5" }}>
                  {service.description}
                </p>
                <button
                  onClick={() => deployService(service.name)}
                  disabled={service.disabled || isDeployed || isDeploying || !cluster}
                  style={{
                    width: "100%",
                    padding: "10px",
                    backgroundColor: service.disabled || isDeployed || !cluster ? "#e5e7eb" : "#2563eb",
                    color: service.disabled || isDeployed || !cluster ? "#9ca3af" : "white",
                    border: "none",
                    borderRadius: "4px",
                    cursor: service.disabled || isDeployed || !cluster ? "not-allowed" : "pointer",
                    fontSize: "14px",
                    fontWeight: "500",
                  }}
                >
                  {isDeploying
                    ? "Deploying..."
                    : isDeployed
                    ? "Already Deployed"
                    : service.disabled
                    ? "Coming Soon"
                    : "Deploy"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
