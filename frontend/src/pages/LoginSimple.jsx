import { useState } from "react";

export default function Login() {
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    try {
      const response = await fetch("http://localhost:3000/v1/auth/login-url");
      const data = await response.json();
      
      sessionStorage.setItem("pkce_code_verifier", data.code_verifier);
      window.location.href = data.login_url;
    } catch (err) {
      alert("Login error: " + err.message);
      setLoading(false);
    }
  };

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
        maxWidth: "300px"
      }}>
        <h1 style={{ margin: "0 0 30px 0", color: "#333" }}>StreamLink</h1>
        <button
          onClick={handleLogin}
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
      </div>
    </div>
  );
}
