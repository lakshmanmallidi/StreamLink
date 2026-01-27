import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

export default function Services() {
  const [services, setServices] = useState([]);
  const [cluster, setCluster] = useState(null);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState(null);
  const [deploymentPlan, setDeploymentPlan] = useState(null);
  const [showPlanModal, setShowPlanModal] = useState(false);
  const [deletePlan, setDeletePlan] = useState(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [bootstrapStatus, setBootstrapStatus] = useState(null);
  const [migrating, setMigrating] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchCluster();
    fetchServices();
    fetchBootstrapStatus();
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

  const fetchBootstrapStatus = async () => {
    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch("http://localhost:3000/v1/bootstrap/status", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      setBootstrapStatus(data);
    } catch (err) {
      console.error("Error fetching bootstrap status:", err);
    }
  };

  const migrateToPostgres = async () => {
    if (!confirm("Migrate to PostgreSQL?\n\nThis will copy all data from SQLite to PostgreSQL. After migration completes, you'll need to restart the backend.")) {
      return;
    }

    setMigrating(true);
    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch("http://localhost:3000/v1/bootstrap/migrate", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Migration failed");
      }

      const result = await response.json();
      alert(`✅ Migration completed!\n\n${result.message}\n\nClusters migrated: ${result.clusters_migrated}\nServices migrated: ${result.services_migrated}\n\nPlease restart the backend now.`);
      await fetchBootstrapStatus();
    } catch (err) {
      alert(`Migration failed: ${err.message}`);
    } finally {
      setMigrating(false);
    }
  };

  const deployService = async (serviceName) => {
    if (!cluster) {
      alert("Please configure a Kubernetes cluster first");
      navigate("/clusters/add");
      return;
    }

    // First, get the deployment plan
    try {
      const token = localStorage.getItem("access_token");
      const planResponse = await fetch("http://localhost:3000/v1/services/deployment-plan", {
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

      if (!planResponse.ok) {
        const error = await planResponse.json();
        throw new Error(error.detail || "Failed to get deployment plan");
      }

      const plan = await planResponse.json();
      
      // If service is already installed
      if (services.some(s => s.name === serviceName)) {
        alert(`${plan.target_display_name} is already deployed.`);
        return;
      }

      // If there are dependencies to install, show the plan
      if (plan.total_to_install > 0) {
        setDeploymentPlan({ ...plan, serviceName });
        setShowPlanModal(true);
      } else {
        // No dependencies, deploy directly
        await executeDeploy(serviceName);
      }
    } catch (err) {
      console.error("Error getting deployment plan:", err);
      alert(`Failed to prepare deployment: ${err.message}`);
    }
  };

  const executeDeploy = async (serviceName) => {
    setDeploying(serviceName);
    setShowPlanModal(false);
    
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
      alert(`${serviceName} and all dependencies deployed successfully!`);
    } catch (err) {
      console.error("Error deploying service:", err);
      alert(`Failed to deploy ${serviceName}: ${err.message}`);
    } finally {
      setDeploying(null);
      setDeploymentPlan(null);
    }
  };

  const deleteService = async (service) => {
    try {
      const token = localStorage.getItem("access_token");
      
      // First, get the delete plan to see what will be deleted
      const planResponse = await fetch(`http://localhost:3000/v1/services/${service.id}/delete-plan`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      
      if (!planResponse.ok) {
        throw new Error("Failed to get delete plan");
      }
      
      const plan = await planResponse.json();
      
      // Show the delete confirmation modal
      setDeletePlan(plan);
      setShowDeleteModal(true);
    } catch (err) {
      console.error("Error getting delete plan:", err);
      alert("Failed to get delete plan");
    }
  };

  const executeDelete = async () => {
    if (!deletePlan) return;

    try {
      const token = localStorage.getItem("access_token");
      
      // Delete with cascade if there are dependents
      const cascade = deletePlan.dependents.length > 0;
      const response = await fetch(`http://localhost:3000/v1/services/${deletePlan.target.id}?cascade=${cascade}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      
      const result = await response.json();
      
      setShowDeleteModal(false);
      setDeletePlan(null);
      await fetchServices();
      
      // Check if restart is required (for postgres deletion)
      if (result.restart_required) {
        alert(`⚠️ RESTART REQUIRED\n\n${result.message}\n\n${result.warning || ''}`);
      } else if (deletePlan.total_deletions > 1) {
        alert(`Successfully deleted ${deletePlan.total_deletions} services`);
      } else {
        alert(result.message || "Service deleted successfully");
      }
    } catch (err) {
      console.error("Error deleting service:", err);
      alert("Failed to delete service");
    }
  };

  const availableServices = [
    {
      name: "postgres",
      displayName: "PostgreSQL Database",
      description: "Production database for StreamLink. Enables migration from SQLite and is required for Keycloak authentication.",
      icon: "🐘",
      dependencies: [],
    },
    {
      name: "keycloak",
      displayName: "Keycloak (Authentication)",
      description: "Identity and Access Management. Enables OAuth2 authentication for StreamLink. Requires PostgreSQL.",
      icon: "🔐",
      dependencies: ["postgres"],
    },
    {
      name: "kafka",
      displayName: "Apache Kafka",
      description: "Distributed event streaming platform (KRaft mode). No dependencies required.",
      icon: "🔄",
      dependencies: [],
    },
    {
      name: "schema-registry",
      displayName: "Schema Registry",
      description: "Confluent Schema Registry for managing Avro, JSON, and Protobuf schemas. Requires Kafka.",
      icon: "📋",
      dependencies: ["kafka"],
    },
    {
      name: "kafka-connect",
      displayName: "Kafka Connect",
      description: "Distributed framework for connecting Kafka with external systems. Requires Kafka and Schema Registry.",
      icon: "🔌",
      dependencies: ["kafka", "schema-registry"],
    },
    {
      name: "ksqldb",
      displayName: "ksqlDB",
      description: "Streaming SQL engine for Apache Kafka. Requires Kafka, Schema Registry, and Kafka Connect.",
      icon: "💾",
      dependencies: ["kafka", "schema-registry", "kafka-connect"],
    },
    {
      name: "kafbat-ui",
      displayName: "Kafbat UI",
      description: "Web UI for managing and monitoring Apache Kafka clusters. Provides unified interface for all services.",
      icon: "🎛️",
      dependencies: ["kafka", "schema-registry", "kafka-connect", "ksqldb", "keycloak"],
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

      {/* Deployment Plan Modal */}
      {showPlanModal && deploymentPlan && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setShowPlanModal(false)}
        >
          <div
            style={{
              backgroundColor: "white",
              borderRadius: "8px",
              padding: "30px",
              maxWidth: "500px",
              width: "90%",
              maxHeight: "80vh",
              overflow: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 15px 0", color: "#1e3a8a", fontSize: "20px" }}>
              Deployment Plan
            </h3>
            
            <div
              style={{
                backgroundColor: "#eff6ff",
                border: "1px solid #bfdbfe",
                borderRadius: "6px",
                padding: "15px",
                marginBottom: "20px",
                fontSize: "14px",
                color: "#1e3a8a",
              }}
            >
              ℹ️ {deploymentPlan.message}
            </div>

            {deploymentPlan.dependencies.length > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <h4 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#6b7280" }}>
                  Dependencies
                </h4>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {deploymentPlan.dependencies.map((dep, idx) => (
                    <div
                      key={dep.name}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        padding: "12px",
                        backgroundColor: dep.status === "installed" ? "#f0fdf4" : "#fef3c7",
                        border: `1px solid ${dep.status === "installed" ? "#bbf7d0" : "#fcd34d"}`,
                        borderRadius: "6px",
                        fontSize: "14px",
                      }}
                    >
                      <span style={{ fontWeight: "600", color: "#6b7280", minWidth: "20px" }}>
                        {idx + 1}.
                      </span>
                      <span style={{ flex: 1, color: "#1e3a8a" }}>
                        {dep.display_name}
                      </span>
                      <span
                        style={{
                          padding: "2px 8px",
                          backgroundColor: dep.status === "installed" ? "#22c55e" : "#f59e0b",
                          color: "white",
                          borderRadius: "10px",
                          fontSize: "11px",
                          fontWeight: "500",
                        }}
                      >
                        {dep.status === "installed" ? "✓ Installed" : "Will Install"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div
              style={{
                padding: "12px",
                backgroundColor: "#dbeafe",
                border: "1px solid #93c5fd",
                borderRadius: "6px",
                marginBottom: "20px",
                fontSize: "14px",
                color: "#1e3a8a",
                fontWeight: "500",
              }}
            >
              → {deploymentPlan.target_display_name} (Target)
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                onClick={() => executeDeploy(deploymentPlan.serviceName)}
                style={{
                  flex: 1,
                  padding: "12px",
                  backgroundColor: "#2563eb",
                  color: "white",
                  border: "none",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "14px",
                  fontWeight: "500",
                }}
              >
                Deploy All ({deploymentPlan.total_to_install + 1} service{deploymentPlan.total_to_install > 0 ? "s" : ""})
              </button>
              <button
                onClick={() => {
                  setShowPlanModal(false);
                  setDeploymentPlan(null);
                }}
                style={{
                  padding: "12px 20px",
                  backgroundColor: "white",
                  color: "#6b7280",
                  border: "1px solid #e5e7eb",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && deletePlan && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setShowDeleteModal(false)}
        >
          <div
            style={{
              backgroundColor: "white",
              borderRadius: "8px",
              padding: "30px",
              maxWidth: "500px",
              width: "90%",
              maxHeight: "80vh",
              overflow: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 15px 0", color: "#dc2626", fontSize: "20px" }}>
              ⚠️ Confirm Deletion
            </h3>
            
            <div
              style={{
                backgroundColor: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: "6px",
                padding: "15px",
                marginBottom: "20px",
                fontSize: "14px",
                color: "#991b1b",
              }}
            >
              You are about to delete <strong>{deletePlan.target.display_name}</strong>
            </div>

            {deletePlan.dependents.length > 0 && (
              <div style={{ marginBottom: "20px" }}>
                <div
                  style={{
                    backgroundColor: "#fef3c7",
                    border: "1px solid #fcd34d",
                    borderRadius: "6px",
                    padding: "15px",
                    marginBottom: "15px",
                    fontSize: "14px",
                    color: "#92400e",
                    fontWeight: "500",
                  }}
                >
                  ⚠️ Warning: The following dependent services will also be deleted:
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {deletePlan.dependents.map((dep, idx) => (
                    <div
                      key={dep.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        padding: "12px",
                        backgroundColor: "#fee2e2",
                        border: "1px solid #fecaca",
                        borderRadius: "6px",
                        fontSize: "14px",
                      }}
                    >
                      <span style={{ fontWeight: "600", color: "#dc2626", minWidth: "20px" }}>
                        {idx + 1}.
                      </span>
                      <span style={{ flex: 1, color: "#991b1b" }}>
                        {dep.display_name}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div
              style={{
                padding: "12px",
                backgroundColor: "#fee2e2",
                border: "1px solid #fecaca",
                borderRadius: "6px",
                marginBottom: "20px",
                fontSize: "14px",
                color: "#991b1b",
                fontWeight: "500",
              }}
            >
              Total services to delete: {deletePlan.total_deletions}
            </div>

            <div style={{ display: "flex", gap: "10px" }}>
              <button
                onClick={executeDelete}
                style={{
                  flex: 1,
                  padding: "12px",
                  backgroundColor: "#dc2626",
                  color: "white",
                  border: "none",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "14px",
                  fontWeight: "500",
                }}
              >
                Delete All ({deletePlan.total_deletions} service{deletePlan.total_deletions > 1 ? "s" : ""})
              </button>
              <button
                onClick={() => {
                  setShowDeleteModal(false);
                  setDeletePlan(null);
                }}
                style={{
                  padding: "12px 20px",
                  backgroundColor: "white",
                  color: "#6b7280",
                  border: "1px solid #e5e7eb",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "14px",
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

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
                  <div style={{ display: "flex", gap: "10px" }}>
                    {/* Show Migrate button only for postgres when migration is pending */}
                    {service.manifest_name === "postgres" && 
                     bootstrapStatus && 
                     bootstrapStatus.postgres_deployed && 
                     !bootstrapStatus.migration_complete && 
                     bootstrapStatus.ready_for_migration && (
                      <button
                        onClick={migrateToPostgres}
                        disabled={migrating}
                        style={{
                          padding: "8px 16px",
                          backgroundColor: migrating ? "#d1d5db" : "#10b981",
                          color: "white",
                          border: "none",
                          borderRadius: "4px",
                          cursor: migrating ? "not-allowed" : "pointer",
                          fontSize: "13px",
                          fontWeight: "500",
                        }}
                      >
                        {migrating ? "Migrating..." : "Migrate"}
                      </button>
                    )}
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
            const isDeployed = services.some((s) => (s.manifest_name || s.name) === service.name);
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
