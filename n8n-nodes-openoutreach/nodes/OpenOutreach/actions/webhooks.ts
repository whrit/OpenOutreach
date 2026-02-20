import { IDataObject, IExecuteFunctions, INodeExecutionData, INodeProperties, NodeOperationError } from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const webhooksOperations: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['webhooks'] } },
		options: [
			{ name: 'Delete', value: 'delete', description: 'Delete a webhook subscription', action: 'Delete a webhook' },
			{ name: 'Register', value: 'register', description: 'Register a new webhook subscription', action: 'Register a webhook' },
		],
		default: 'register',
	},
];

export const webhooksFields: INodeProperties[] = [
	// ── register fields ───────────────────────────────────────────────────────
	{
		displayName: 'URL',
		name: 'url',
		type: 'string',
		required: true,
		displayOptions: { show: { resource: ['webhooks'], operation: ['register'] } },
		default: '',
		placeholder: 'https://example.com/webhook',
		description: 'The URL that will receive webhook POST requests',
	},
	{
		displayName: 'Events',
		name: 'events',
		type: 'multiOptions',
		required: true,
		displayOptions: { show: { resource: ['webhooks'], operation: ['register'] } },
		options: [
			{ name: 'Job Completed', value: 'job.completed' },
			{ name: 'Job Failed', value: 'job.failed' },
			{ name: 'Profile State Changed', value: 'profile.state_changed' },
		],
		default: [],
		description: 'Which events should trigger this webhook',
	},
	{
		displayName: 'Campaign ID',
		name: 'campaignId',
		type: 'number',
		displayOptions: { show: { resource: ['webhooks'], operation: ['register'] } },
		default: 0,
		description: 'Restrict webhook to a specific campaign. Leave 0 for all campaigns.',
	},

	// ── delete fields ─────────────────────────────────────────────────────────
	{
		displayName: 'Webhook ID',
		name: 'webhookId',
		type: 'number',
		required: true,
		displayOptions: { show: { resource: ['webhooks'], operation: ['delete'] } },
		default: 0,
		description: 'ID of the webhook subscription to delete',
	},
];

export async function executeWebhooks(
	this: IExecuteFunctions,
	i: number,
): Promise<INodeExecutionData[]> {
	const operation = this.getNodeParameter('operation', i) as string;

	if (operation === 'register') {
		const url = this.getNodeParameter('url', i) as string;
		const events = this.getNodeParameter('events', i) as string[];
		const campaignId = this.getNodeParameter('campaignId', i, 0) as number;

		const body: IDataObject = { url, events };
		if (campaignId) {
			body.campaign_id = campaignId;
		}

		const result = (await openOutreachRequest.call(this, 'POST', '/webhooks/', body)) as IDataObject;
		return [{ json: result }];
	}

	if (operation === 'delete') {
		const webhookId = this.getNodeParameter('webhookId', i) as number;
		await openOutreachRequest.call(this, 'DELETE', `/webhooks/${webhookId}/`);
		return [{ json: { deleted: true } }];
	}

	throw new NodeOperationError(this.getNode(), `Unknown webhooks operation: ${operation}`);
}
