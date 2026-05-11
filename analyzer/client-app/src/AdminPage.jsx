import React, { useState, useEffect } from 'react';

function AdminPage() {
  const [providers, setProviders] = useState([]);
  const [newProviderName, setNewProviderName] = useState('');
  const [newProviderUrl, setNewProviderUrl] = useState('');
  const [newProviderKey, setNewProviderKey] = useState('');
  const [newModelName, setNewModelName] = useState('');

  const [prompts, setPrompts] = useState([]);
  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptDescription, setNewPromptDescription] = useState('');
  const [newVersionNumber, setNewVersionNumber] = useState(1);
  const [newVersionText, setNewVersionText] = useState('');

  const [allModels, setAllModels] = useState([]);
  const [selectedIngestModel, setSelectedIngestModel] = useState('');
  const [ingestStatus, setIngestStatus] = useState('');
  const [kpFilesDir, setKpFilesDir] = useState('');
  const [kpFiles, setKpFiles] = useState([]);
  const [kpSelectedFiles, setKpSelectedFiles] = useState([]);
  const [kpIngestStatus, setKpIngestStatus] = useState('');

  const fetchProviders = async () => {
    const response = await fetch('http://localhost:8000/api/providers/');
    setProviders(await response.json());
  };

  const fetchPrompts = async () => {
    const response = await fetch('http://localhost:8000/api/prompts/');
    setPrompts(await response.json());
  };

  const fetchAllModels = async () => {
    const response = await fetch('http://localhost:8000/api/all-models');
    const data = await response.json();
    setAllModels(data);
    if (data.length > 0) {
      setSelectedIngestModel(data[0].id);
    }
  };

  const fetchKnowledgePointFiles = async () => {
    const response = await fetch('http://localhost:8000/api/knowledge-points/ingest/files');
    if (!response.ok) {
      setKpFilesDir('');
      setKpFiles([]);
      return;
    }
    const data = await response.json();
    setKpFilesDir(data.directory || '');
    setKpFiles(data.files || []);
    setKpSelectedFiles([]);
  };

  useEffect(() => {
    fetchProviders();
    fetchPrompts();
    fetchAllModels();
    fetchKnowledgePointFiles();
  }, []);

  const handleAddProvider = async (e) => {
    e.preventDefault();
    await fetch('http://localhost:8000/api/providers/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newProviderName, api_url: newProviderUrl, api_key: newProviderKey }),
    });
    fetchProviders();
    fetchAllModels(); // Refresh models list as well
    setNewProviderName('');
    setNewProviderUrl('');
    setNewProviderKey('');
  };

  const handleAddModel = async (e, providerId) => {
    e.preventDefault();
    await fetch(`http://localhost:8000/api/providers/${providerId}/models/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newModelName }),
    });
    fetchProviders();
    fetchAllModels(); // Refresh models list as well
    setNewModelName('');
  };

  const handleAddPrompt = async (e) => {
    e.preventDefault();
    await fetch('http://localhost:8000/api/prompts/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newPromptName, description: newPromptDescription }),
    });
    fetchPrompts();
    setNewPromptName('');
    setNewPromptDescription('');
  };

  const handleAddVersion = async (e, promptId) => {
    e.preventDefault();
    await fetch(`http://localhost:8000/api/prompts/${promptId}/versions/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: newVersionNumber, prompt_text: newVersionText }),
    });
    fetchPrompts();
    setNewVersionNumber(1);
    setNewVersionText('');
  };

  const handleTriggerIngestion = async () => {
    if (!selectedIngestModel) {
      alert("请先选择用于摄入的模型。");
      return;
    }
    setIngestStatus('正在启动摄入任务…');
    const response = await fetch('http://localhost:8000/api/ingest-knowledge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: selectedIngestModel }),
    });
    const data = await response.json();
    setIngestStatus(`摄入任务已启动，任务编号：${data.task_id}。请在任务页面查看进度。`);
  };

  const toggleKpSelectedFile = (filename) => {
    setKpSelectedFiles((prev) => {
      if (prev.includes(filename)) {
        return prev.filter((item) => item !== filename);
      }
      return [...prev, filename];
    });
  };

  const handleTriggerKnowledgePointsIngestion = async () => {
    if (!selectedIngestModel) {
      alert("请先选择用于摄入的模型。");
      return;
    }
    if (!kpSelectedFiles.length) {
      alert("请先选择要摄入的文档。");
      return;
    }
    setKpIngestStatus('正在启动专题/知识点文档摄入任务…');
    const response = await fetch('http://localhost:8000/api/knowledge-points/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: selectedIngestModel, files: kpSelectedFiles }),
    });
    const data = await response.json();
    if (!response.ok) {
      setKpIngestStatus(`启动失败：${data?.detail || '未知错误'}`);
      return;
    }
    setKpIngestStatus(`摄入任务已启动，任务编号：${data.task_id}。你可以在后端任务接口查询状态。`);
  };

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-6">管理后台</h1>

      <div className="bg-white p-6 rounded-lg shadow-md mb-8">
        <h2 className="text-2xl font-bold mb-4">知识库目录摄入（旧入口）</h2>
        <div className="mb-4">
          <label htmlFor="ingest-model-select" className="block text-sm font-medium text-gray-700 mb-1">选择用于摄入的模型：</label>
          <select
            id="ingest-model-select"
            value={selectedIngestModel}
            onChange={(e) => setSelectedIngestModel(e.target.value)}
            className="w-full p-2 border rounded-md"
          >
            {allModels.map((model) => (
              <option key={model.id} value={model.id}>
                {model.provider.name} - {model.name}
              </option>
            ))}
          </select>
        </div>
        <button onClick={handleTriggerIngestion} className="bg-purple-600 hover:bg-purple-800 text-white font-bold py-2 px-4 rounded">
          启动摄入
        </button>
        {ingestStatus && <p className="mt-4 text-sm text-gray-600">{ingestStatus}</p>}
      </div>

      <div className="bg-white p-6 rounded-lg shadow-md mb-8">
        <div className="flex items-center justify-between gap-3 mb-4">
          <h2 className="text-2xl font-bold">专题/知识点文档摄入</h2>
          <button
            onClick={fetchKnowledgePointFiles}
            className="bg-slate-700 hover:bg-slate-900 text-white font-bold py-2 px-4 rounded"
          >
            刷新文档列表
          </button>
        </div>
        <p className="text-sm text-gray-600 mb-4">
          摄入目录：<span className="font-mono">{kpFilesDir || '（未获取到目录信息）'}</span>
        </p>

        {!kpFiles.length ? (
          <div className="text-sm text-gray-600">
            未发现可摄入文档（仅支持 PDF、DOCX、TXT）。如功能未启用，请在后端启用知识点开关。
          </div>
        ) : (
          <div className="border rounded-md p-3 max-h-64 overflow-auto mb-4">
            {kpFiles.map((filename) => (
              <label key={filename} className="flex items-center gap-2 py-1">
                <input
                  type="checkbox"
                  checked={kpSelectedFiles.includes(filename)}
                  onChange={() => toggleKpSelectedFile(filename)}
                />
                <span className="font-mono text-sm">{filename}</span>
              </label>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleTriggerKnowledgePointsIngestion}
            className="bg-emerald-600 hover:bg-emerald-800 text-white font-bold py-2 px-4 rounded"
            disabled={!kpSelectedFiles.length}
          >
            启动专题/知识点摄入
          </button>
          <div className="text-sm text-gray-600">
            已选中：{kpSelectedFiles.length} 个
          </div>
        </div>
        {kpIngestStatus && <p className="mt-4 text-sm text-gray-600">{kpIngestStatus}</p>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div>
          <div className="bg-white p-6 rounded-lg shadow-md mb-6">
            <h2 className="text-2xl font-bold mb-4">新增接口服务商</h2>
            <form onSubmit={handleAddProvider}>
              <div className="mb-4"><input type="text" value={newProviderName} onChange={(e) => setNewProviderName(e.target.value)} placeholder="服务商名称" className="w-full px-3 py-2 border rounded-md" required /></div>
              <div className="mb-4"><input type="text" value={newProviderUrl} onChange={(e) => setNewProviderUrl(e.target.value)} placeholder="接口地址" className="w-full px-3 py-2 border rounded-md" required /></div>
              <div className="mb-4"><input type="password" value={newProviderKey} onChange={(e) => setNewProviderKey(e.target.value)} placeholder="接口密钥" className="w-full px-3 py-2 border rounded-md" required /></div>
              <button type="submit" className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">添加服务商</button>
            </form>
          </div>
          <div>
            <h2 className="text-2xl font-bold mb-4">已配置的服务商</h2>
            <div className="space-y-4">
              {providers.map((provider) => (
                <div key={provider.id} className="bg-white p-4 rounded-lg shadow-md">
                  <p className="font-bold text-xl">{provider.name}</p>
                  <p className="text-sm text-gray-600 mb-2">{provider.api_url}</p>
                  {provider.display_api_key && <p className="text-sm font-mono text-gray-500">接口密钥（展示）：{provider.display_api_key}</p>}
                  <h3 className="font-semibold mt-2">模型：</h3>
                  <ul className="list-disc list-inside pl-4">{provider.models.map((model) => (<li key={model.id}>{model.name}</li>))}</ul>
                  <form onSubmit={(e) => handleAddModel(e, provider.id)} className="mt-2 flex gap-2">
                    <input type="text" value={newModelName} onChange={(e) => setNewModelName(e.target.value)} placeholder="新模型名称" className="flex-grow px-3 py-1 border rounded-md text-sm" />
                    <button type="submit" className="bg-green-500 hover:bg-green-700 text-white font-bold py-1 px-3 rounded text-sm">添加模型</button>
                  </form>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div>
          <div className="bg-white p-6 rounded-lg shadow-md mb-6">
            <h2 className="text-2xl font-bold mb-4">新增提示词分类</h2>
            <form onSubmit={handleAddPrompt}>
              <div className="mb-4"><input type="text" value={newPromptName} onChange={(e) => setNewPromptName(e.target.value)} placeholder="提示词名称" className="w-full px-3 py-2 border rounded-md" required /></div>
              <div className="mb-4"><input type="text" value={newPromptDescription} onChange={(e) => setNewPromptDescription(e.target.value)} placeholder="描述" className="w-full px-3 py-2 border rounded-md" /></div>
              <button type="submit" className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">添加提示词</button>
            </form>
          </div>
          <div>
            <h2 className="text-2xl font-bold mb-4">已存在的提示词</h2>
            <div className="space-y-4">
              {prompts.map((prompt) => (
                <div key={prompt.id} className="bg-white p-4 rounded-lg shadow-md">
                  <p className="font-bold text-xl">{prompt.name}</p>
                  <p className="text-sm text-gray-600 mb-2">{prompt.description}</p>
                  <h3 className="font-semibold mt-2">版本：</h3>
                  <ul className="list-disc list-inside pl-4">{prompt.versions.map((version) => (<li key={version.id}>版本{version.version}：{version.prompt_text.substring(0, 50)}...</li>))}</ul>
                  <form onSubmit={(e) => handleAddVersion(e, prompt.id)} className="mt-2">
                    <div className="flex gap-2 mb-2">
                      <input type="number" value={newVersionNumber} onChange={(e) => setNewVersionNumber(parseInt(e.target.value, 10))} placeholder="版本号" className="w-1/4 px-3 py-1 border rounded-md text-sm" />
                      <textarea value={newVersionText} onChange={(e) => setNewVersionText(e.target.value)} placeholder="提示词内容" className="flex-grow px-3 py-1 border rounded-md text-sm" rows="2"></textarea>
                    </div>
                    <button type="submit" className="bg-green-500 hover:bg-green-700 text-white font-bold py-1 px-3 rounded text-sm">添加版本</button>
                  </form>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AdminPage;
