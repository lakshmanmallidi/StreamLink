import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../config";

export default function Login() {
  const [loading, setLoading] = useState(false);
  const [authStatus, setAuthStatus] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    // Check auth status
    fetch(`${API_BASE_URL}/v1/auth/status`)
      .then((res) => res.json())
      .then((data) => setAuthStatus(data))
      .catch(() => setAuthStatus({ auth_enabled: true }));
  }, []);

  const handleKeycloakLogin = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/v1/auth/login-url`);
      const data = await response.json();
      
      sessionStorage.setItem("pkce_code_verifier", data.code_verifier);
      window.location.href = data.login_url;
    } catch (err) {
      alert("Login error: " + err.message);
      setLoading(false);
    }
  };

  const handleSimpleLogin = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/v1/auth/simple-login`, {
        method: "POST",
      });
      const data = await response.json();
      
      localStorage.setItem("access_token", data.access_token);
      localStorage.setItem("user", JSON.stringify(data.user));
      navigate("/");
    } catch (err) {
      alert("Login error: " + err.message);
      setLoading(false);
    }
  };

  if (!authStatus) {
    return <div style={{ padding: "40px", textAlign: "center" }}>Loading...</div>;
  }

  return (
    <div style={{ 
      display: "flex", 
      alignItems: "center", 
      justifyContent: "center", 
      height: "100vh",
      backgroundColor: "#f0f0f0"
    }}>
      <div style={{
        backgroundColor: "white",
        padding: "40px",
        borderRadius: "8px",
        boxShadow: "0 2px 10px rgba(0,0,0,0.1)",
        textAlign: "center",
        width: "100%",
        maxWidth: "350px"
      }}>
        <h1 style={{ margin: "0 0 10px 0", color: "#333" }}>StreamLink</h1>
        <p style={{ color: "#666", fontSize: "14px", marginBottom: "30px" }}>
          {authStatus.message}
        </p>

        {authStatus.auth_enabled ? (
          <button
            onClick={handleKeycloakLogin}
            disabled={loading}
            style={{
              width: "100%",
              padding: "12px",
              backgroundColor: "#007bff",
              color: "white",
              border: "none",
              borderRadius: "4px",
              fontSize: "16px",
              cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.6 : 1
            }}
          >
            {loading ? "Redirecting..." : "Login with Keycloak"}
          </button>
        ) : (
          <button
            onClick={handleSimpleLogin}
            disabled={loading}
            style={{
              width: "100%",
              padding: "12px",
              backgroundColor: "#28a745",
              color: "white",
              border: "none",
              borderRadius: "4px",
              fontSize: "16px",
              cursor: loading ? "not-allowed" : "pointer",
              opacity: loading ? 0.6 : 1
            }}
          >
            {loading ? "Logging in..." : "Continue"}
          </button>
        )}
      </div>
    </div>
  );
}
