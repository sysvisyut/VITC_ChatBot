import { useState, useEffect, useRef } from "react";
import { Header } from "@/components/Header";
import { MessageBubble } from "@/components/MessageBubble";
import { TypingIndicator } from "@/components/TypingIndicator";
import { SuggestedPrompts } from "@/components/SuggestedPrompts";
import { ChatInput } from "@/components/ChatInput";
import { Message, ChatSession } from "@/types/chat";
import { chatApi } from "@/lib/api";
import { chatStorage } from "@/lib/storage";
import { toast } from "@/hooks/use-toast";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState(() => `session_${Date.now()}`);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Load saved session on mount (optional - can be expanded later)
  useEffect(() => {
    // For now, start fresh each time. Can add session persistence later.
  }, []);

  const handleSendMessage = async (content: string) => {
    const userMessage: Message = {
      id: `msg_${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      let isFirstChunk = true;
      const assistantId = `msg_${Date.now()}_assistant`;

      await chatApi.streamMessage(
        content,
        (textChunk) => {
          if (isFirstChunk) {
            setIsLoading(false);
            isFirstChunk = false;
            setMessages((prev) => [
              ...prev,
              {
                id: assistantId,
                role: "assistant",
                content: textChunk,
                timestamp: new Date(),
              }
            ]);
          } else {
            setMessages((prev) => 
              prev.map(m => m.id === assistantId ? { ...m, content: m.content + textChunk } : m)
            );
          }
        },
        (sources, confidence) => {
          setMessages((prev) => {
            let updatedMessages;
            if (isFirstChunk) {
              setIsLoading(false);
              isFirstChunk = false;
              updatedMessages = [
                ...prev,
                {
                  id: assistantId,
                  role: "assistant",
                  content: "",
                  timestamp: new Date(),
                  sources,
                  confidence
                }
              ];
            } else {
              updatedMessages = prev.map(m => 
                m.id === assistantId ? { ...m, sources, confidence } : m
              );
            }
            
            // Save to localStorage
            const session: ChatSession = {
              id: currentSessionId,
              title: updatedMessages.length <= 2 ? content.slice(0, 50) : `Chat ${currentSessionId}`,
              messages: updatedMessages,
              createdAt: new Date(),
              updatedAt: new Date(),
            };
            chatStorage.saveSession(session);
            
            return updatedMessages;
          });
        }
      );
    } catch (error) {
      setIsLoading(false);
      toast({
        title: "Error",
        description: error instanceof Error ? error.message : "Failed to get response",
        variant: "destructive",
      });
    }
  };

  const handleNewChat = () => {
    if (messages.length > 0) {
      const confirmNew = window.confirm(
        "Start a new chat? Current conversation will be saved."
      );
      if (!confirmNew) return;
    }
    setMessages([]);
    setCurrentSessionId(`session_${Date.now()}`);
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header onNewChat={handleNewChat} />

      <main className="flex-1 overflow-y-auto pb-32">
        <div className="container mx-auto px-4 py-8">
          {messages.length === 0 ? (
            <div className="min-h-[60vh] flex items-center justify-center">
              <SuggestedPrompts onSelectPrompt={handleSendMessage} />
            </div>
          ) : (
            <div className="max-w-4xl mx-auto">
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  role={message.role}
                  content={message.content}
                  timestamp={message.timestamp}
                  sources={message.sources}
                  confidence={message.confidence}
                />
              ))}
              {isLoading && <TypingIndicator />}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </main>

      <ChatInput onSendMessage={handleSendMessage} disabled={isLoading} />
    </div>
  );
}
