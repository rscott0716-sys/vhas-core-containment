# Add this node entry inside the "production_nodes" dictionary of your python installer script:

    "vhas_mcp_schema.json": """
{
  "$schema": "http://json-schema.org",
  "title": "VHAS_MCP_Server_Schema",
  "type": "object",
  "properties": {
    "tools": {
      "type": "array",
      "default": [
        {
          "name": "evaluate_state_vector",
          "description": "Calculates real-time values for Homeostatic Balance (H), Affiliative Resonance (R), and Thermodynamic Compute Cost (C)."
        }
      ]
    }
  }
}
""".strip(),
