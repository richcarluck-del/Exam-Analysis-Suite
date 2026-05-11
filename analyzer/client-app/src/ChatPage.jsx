import React, { useState, useEffect } from 'react';

function ChatPage() {
  const [allModels, setAllModels] = useState([]);
  const [selectedAskModel, setSelectedAskModel] = useState('');
  const [question, setQuestion] = useState('');
  const [conversation, setConversation] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchAllModels = async () => {
    const response = await fetch('http://localhost:8000/api/all-models');
    const data = await response.json();
    setAllModels(data);
    if (data.length > 0) {
      setSelectedAskModel(data[0].id);
    }
  };

  useEffect(() => {
    fetchAllModels();
  }, []);

  const handleAskQuestion = async (e) => {
    e.preventDefault();
    if (!question.trim() || !selectedAskModel) return;

    const userMessage = { sender: 'user', text: question };
    setConversation(prev => [...prev, userMessage]);
    setIsLoading(true);
    setQuestion('');

    const response = await fetch('http://localhost:8000/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: question, model_id: selectedAskModel }),
    });
    const data = await response.json();
    
    const botMessage = { sender: 'bot', text: data.answer, context: data.context };
    setConversation(prev => [...prev, botMessage]);
    setIsLoading(false);
  };

  return (
    <div className="container mx-auto p-4 flex flex-col h-screen bg-gray-50">
      <h1 className="text-3xl font-bold mb-6 text-center">知识库问答</h1>
      
      <div className="mb-4 flex items-center justify-center gap-4">
          <label htmlFor="ask-model-select" className="block text-sm font-medium text-gray-700">选择用于回答的模型：</label>
          <select
            id="ask-model-select"
            value={selectedAskModel}
            onChange={(e) => setSelectedAskModel(e.target.value)}
            className="p-2 border rounded-md"
          >
            {allModels.map((model) => (
              <option key={model.id} value={model.id}>
                {model.provider.name} - {model.name}
              </option>
            ))}
          </select>
      </div>

      <div className="flex-grow bg-white p-6 rounded-lg shadow-md overflow-y-auto mb-4">
        <div className="space-y-4">
          {conversation.map((msg, index) => (
            <div key={index} className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-lg px-4 py-2 rounded-lg shadow ${msg.sender === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-800'}`}>
                {msg.text}
                {msg.sender === 'bot' && msg.context && (
                  <details className="mt-2 text-xs">
                    <summary className="cursor-pointer font-semibold">查看引用内容</summary>
                    <pre className="whitespace-pre-wrap p-2 bg-gray-100 text-gray-700 rounded-md mt-1">
                      {msg.context}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          ))}
          {isLoading && (
             <div className="flex justify-start">
                <div className="max-w-lg px-4 py-2 rounded-lg shadow bg-gray-200 text-gray-800">
                    正在思考…
                </div>
            </div>
          )}
        </div>
      </div>

      <form onSubmit={handleAskQuestion} className="flex gap-4">
        <input 
          type="text" 
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="请输入你的问题…"
          className="flex-grow px-4 py-2 border rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={isLoading}
        />
        <button 
          type="submit" 
          className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded-full disabled:bg-blue-300"
          disabled={isLoading}
        >
          {isLoading ? '…' : '提问'}
        </button>
      </form>
    </div>
  );
}

export default ChatPage;
