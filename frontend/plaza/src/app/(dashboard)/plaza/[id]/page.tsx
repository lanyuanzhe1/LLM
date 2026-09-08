import { notFound } from 'next/navigation';

import AgentChat from '@/views/agents/AgentChat';
import { getAgent } from '@/configs/agents';

type PageProps = {
	params: { id: string };
};

export default function AgentPage({ params }: PageProps) {
	const agent = getAgent(params.id);

	if (!agent) notFound();

	return <AgentChat agent={agent} />;
}
