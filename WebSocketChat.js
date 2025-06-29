import React, { useRef, useState } from "react";

// Use deployed URL if available, otherwise use local
const DEPLOYED_WS_BASE_URL = "wss://student-managment-api-ilmg.onrender.com/ws-demo/ws/chat/";
const LOCAL_WS_BASE_URL =
  (window.location.protocol === "https:" ? "wss://" : "ws://") +
  window.location.host +
  "/ws-demo/ws/chat/";

const WS_BASE_URL =
  window.location.hostname === "student-managment-api-ilmg.onrender.com"
    ? DEPLOYED_WS_BASE_URL
    : LOCAL_WS_BASE_URL;

export default function WebSocketChat() {
  const [senderId, setSenderId] = useState("");
  const [receiverId, setReceiverId] = useState("");
  const [msg, setMsg] = useState("");
  const [log, setLog] = useState([]);
  const ws = useRef(null);
  const lastSender = useRef("");

  // Connect WebSocket when senderId changes
  const connectWS = () => {
    if (!senderId) return;
    if (
      ws.current &&
      ws.current.readyState === 1 &&
      lastSender.current === senderId
    )
      return;
    if (ws.current) ws.current.close();
    ws.current = new window.WebSocket(WS_BASE_URL + senderId);
    lastSender.current = senderId;
    ws.current.onopen = () => {
      setLog((l) => [...l, "WebSocket connected"]);
    };
    ws.current.onmessage = (event) => {
      try {
        const obj = JSON.parse(event.data);
        if (obj.typing && obj.sender_id) {
          setLog((l) => [
            ...l,
            <i key={l.length}>{obj.sender_id} is typing...</i>,
          ]);
        } else if (obj.msg && obj.sender_id) {
          const label = obj.sender_id === senderId ? "You" : obj.sender_id;
          setLog((l) => [...l, <b key={l.length}>{label}:</b>, " " + obj.msg]);
        }
      } catch {
        setLog((l) => [...l, event.data]);
      }
    };
    ws.current.onclose = () => {
      setLog((l) => [...l, "WebSocket closed"]);
    };
  };

  // Send message
  const sendMsg = () => {
    if (!ws.current || ws.current.readyState !== 1) {
      connectWS();
      setTimeout(sendMsg, 300);
      return;
    }
    const payload = JSON.stringify({
      sender_id: senderId,
      receiver_id: receiverId,
      msg: msg,
      typing: false,
    });
    ws.current.send(payload);
    setMsg("");
  };

  // Typing notification
  let typingTimeout = useRef(null);
  const notifyTyping = () => {
    clearTimeout(typingTimeout.current);
    typingTimeout.current = setTimeout(() => {
      if (
        !ws.current ||
        ws.current.readyState !== 1 ||
        !senderId ||
        !receiverId
      )
        return;
      const payload = JSON.stringify({
        sender_id: senderId,
        receiver_id: receiverId,
        typing: true,
      });
      ws.current.send(payload);
    }, 100);
  };

  // Reconnect when senderId changes
  React.useEffect(() => {
    connectWS();
    // Cleanup on unmount
    return () => {
      if (ws.current) ws.current.close();
    };
    // eslint-disable-next-line
  }, [senderId]);

  return (
    <div style={{ maxWidth: 400, margin: "auto" }}>
      <h2>WebSocket Chat</h2>
      <input
        value={senderId}
        onChange={(e) => setSenderId(e.target.value)}
        placeholder="Sender ID"
        style={{ width: "49%", marginRight: "2%" }}
      />
      <input
        value={receiverId}
        onChange={(e) => setReceiverId(e.target.value)}
        placeholder="Receiver ID"
        style={{ width: "49%" }}
      />
      <div style={{ margin: "10px 0" }}>
        <input
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onInput={notifyTyping}
          placeholder="Type a message..."
          style={{ width: "70%" }}
        />
        <button onClick={sendMsg} style={{ width: "28%", marginLeft: "2%" }}>
          Send
        </button>
      </div>
      <div
        id="log"
        style={{
          maxHeight: 300,
          overflowY: "auto",
          border: "1px solid #ccc",
          padding: 5,
        }}
      >
        {log.map((item, idx) => (
          <div key={idx}>{item}</div>
        ))}
      </div>
    </div>
  );
}
