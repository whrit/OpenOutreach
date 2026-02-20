import { IDataObject, IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest, pollJobUntilDone } from '../helpers';

export const lanesOperations: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['lanes'] } },
		options: [
			{
				name: 'Trigger',
				value: 'trigger',
				description: 'Queue a lane action for the daemon to execute',
			},
		],
		default: 'trigger',
	},
];

export const lanesFields: INodeProperties[] = [
	{
		displayName: 'Lane',
		name: 'lane',
		type: 'options',
		required: true,
		displayOptions: { show: { resource: ['lanes'], operation: ['trigger'] } },
		options: [
			{ name: 'Connect', value: 'connect' },
			{ name: 'Check Pending', value: 'check_pending' },
			{ name: 'Follow Up', value: 'follow_up' },
			{ name: 'Qualify', value: 'qualify' },
			{ name: 'Search', value: 'search' },
		],
		default: 'search',
		description: 'Which automation lane to trigger',
	},
	{
		displayName: 'Campaign ID',
		name: 'campaignId',
		type: 'number',
		required: true,
		displayOptions: { show: { resource: ['lanes'], operation: ['trigger'] } },
		default: 1,
		description: 'ID of the campaign this job belongs to',
	},
	{
		displayName: 'Keyword (Search Lane Only)',
		name: 'keyword',
		type: 'string',
		displayOptions: { show: { resource: ['lanes'], operation: ['trigger'], lane: ['search'] } },
		default: '',
		description: 'LinkedIn People search keyword to use when triggering the search lane',
	},
	{
		displayName: 'Wait for Completion',
		name: 'waitForCompletion',
		type: 'boolean',
		displayOptions: { show: { resource: ['lanes'], operation: ['trigger'] } },
		default: false,
		description:
			'Whether to poll until the job finishes. Can take 30–120 s (browser automation).',
	},
	{
		displayName: 'Timeout (Seconds)',
		name: 'timeoutSeconds',
		type: 'number',
		displayOptions: {
			show: { resource: ['lanes'], operation: ['trigger'], waitForCompletion: [true] },
		},
		default: 300,
		description: 'Maximum number of seconds to wait before raising a timeout error',
	},
];

export async function executeLanes(
	this: IExecuteFunctions,
	i: number,
): Promise<INodeExecutionData[]> {
	const lane = this.getNodeParameter('lane', i) as string;
	const campaignId = this.getNodeParameter('campaignId', i) as number;
	const waitForCompletion = this.getNodeParameter('waitForCompletion', i) as boolean;

	const params: IDataObject = {};
	if (lane === 'search') {
		params.keyword = this.getNodeParameter('keyword', i, '') as string;
	}

	const job = (await openOutreachRequest.call(this, 'POST', `/lanes/${lane}/trigger/`, {
		campaign_id: campaignId,
		params,
	})) as IDataObject;

	if (waitForCompletion) {
		const timeoutSeconds = this.getNodeParameter('timeoutSeconds', i, 300) as number;
		// job_id is a string returned directly by the trigger endpoint
		const result = await pollJobUntilDone(this, job.job_id as string, timeoutSeconds * 1000);
		return [{ json: result }];
	}

	return [{ json: job }];
}
