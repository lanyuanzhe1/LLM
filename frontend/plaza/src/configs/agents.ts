// 智能体广场静态配置：每个条目对应一个在讯飞星辰 Agent 平台发布的智能体。
// url 为平台"分享"生成的免登录访问链接（agent.xfyun.cn/agentbuilder/chat?...）。
// 页面通过 iframe 内嵌该链接，因此新增/更换智能体只需改这里，无需改路由代码。
// 若同时配置了 assistantId（平台发布到 API 的助手 id），该智能体改用自绘聊天界面
// （前端直连 /api/backend/assistant-chat → FastAPI /v1/assistant/chat → 讯飞 WS），不再用 iframe。
export type AgentConfig = {
	id: string;
	name: string;
	description: string;
	category: string;
	icon: string;
	color: string;
	featured: boolean;
	url: string;
	assistantId?: string;
};

export const agents: AgentConfig[] = [
	{
		id: 'grain-knowledge',
		name: '粮食行业知识库智能体',
		description: '粮食行业知识库问答',
		category: '知识库',
		icon: 'ri-book-mark-line',
		color: '#7C3AED',
		featured: true,
		url: 'https://agent.xfyun.cn/agentbuilder/chat?sharekey=85d8b2f955b720d4b188bba1175ae933&botId=5807485',
		assistantId: 'kpevnp8z2ff2_v1'
	},
	{
		id: 'grain-research',
		name: '粮食仓储科研智能体·星廪智枢',
		description: '粮食仓储科研问答',
		category: '科研',
		icon: 'ri-flask-line',
		color: '#2563EB',
		featured: true,
		url: 'https://agent.xfyun.cn/agentbuilder/chat?sharekey=4118df001988f10de46adf63fae40a6e&botId=5807479',
		assistantId: 'khhye2gs67wy_v1'
	},
	{
		id: 'teaching-assistant',
		name: '助教智能体·星廪智枢',
		description: '辅助教学、答疑与备课',
		category: '教学',
		icon: 'ri-presentation-line',
		color: '#059669',
		featured: true,
		url: 'https://agent.xfyun.cn/agentbuilder/chat?sharekey=0554bf42efcb9a1ce5181df224e058b9&botId=5807477',
		assistantId: 'xyzrra1uxi9w_v1'
	},
	{
		id: 'learning-assistant',
		name: '助学智能体·星廪智枢',
		description: '辅助学习、练习与复习',
		category: '学习',
		icon: 'ri-graduation-cap-line',
		color: '#DB2777',
		featured: true,
		url: 'https://agent.xfyun.cn/agentbuilder/chat?sharekey=60cc7cfdcd8623bf707ba62ee070dc17&botId=5807465',
		assistantId: 'xou2bntqeaa5_v1'
	}
];

export const getAgent = (id: string): AgentConfig | undefined => agents.find(a => a.id === id);
