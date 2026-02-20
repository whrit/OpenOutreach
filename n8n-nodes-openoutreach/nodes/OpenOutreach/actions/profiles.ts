import { IDataObject, IExecuteFunctions, INodeExecutionData, INodeProperties } from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const profilesOperations: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['profiles'] } },
		options: [
			{
				name: 'Get Many',
				value: 'getMany',
				description: 'List profiles, optionally filtered by state or campaign',
				action: 'Get many profiles',
			},
			{
				name: 'Get',
				value: 'get',
				description: 'Get a single profile by LinkedIn public ID',
				action: 'Get a profile',
			},
			{
				name: 'Inject',
				value: 'inject',
				description: 'Add LinkedIn profile URLs to the pipeline',
				action: 'Inject profile urls',
			},
		],
		default: 'getMany',
	},
];

export const profilesFields: INodeProperties[] = [
	// ── getMany fields ────────────────────────────────────────────────────────
	{
		displayName: 'State Filter',
		name: 'state',
		type: 'options',
		displayOptions: { show: { resource: ['profiles'], operation: ['getMany'] } },
		options: [
			{ name: 'All', value: '' },
			{ name: 'Completed', value: 'completed' },
			{ name: 'Connected', value: 'connected' },
			{ name: 'Disqualified', value: 'disqualified' },
			{ name: 'Enriched', value: 'enriched' },
			{ name: 'Pending', value: 'pending' },
			{ name: 'Qualified (New)', value: 'new' },
			{ name: 'URL Only (Discovered)', value: 'url_only' },
		],
		default: '',
		description: 'Filter profiles by pipeline state. Leave empty to return all profiles.',
	},
	{
		displayName: 'Campaign ID',
		name: 'campaignIdFilter',
		type: 'number',
		displayOptions: { show: { resource: ['profiles'], operation: ['getMany'] } },
		default: 0,
		description: 'Restrict results to a specific campaign. Leave 0 to return profiles across all campaigns.',
	},

	// ── get fields ────────────────────────────────────────────────────────────
	{
		displayName: 'Public ID',
		name: 'publicId',
		type: 'string',
		required: true,
		displayOptions: { show: { resource: ['profiles'], operation: ['get'] } },
		default: '',
		placeholder: 'john-doe-123',
		description: 'LinkedIn public identifier found in the profile URL (e.g. linkedin.com/in/john-doe-123)',
	},

	// ── inject fields ─────────────────────────────────────────────────────────
	{
		displayName: 'Profile URLs',
		name: 'urls',
		type: 'string',
		typeOptions: { multipleValues: true },
		required: true,
		displayOptions: { show: { resource: ['profiles'], operation: ['inject'] } },
		default: [],
		placeholder: 'https://www.linkedin.com/in/john-doe/',
		description: 'One or more LinkedIn profile URLs to add to the pipeline',
	},
	{
		displayName: 'Campaign ID',
		name: 'campaignId',
		type: 'number',
		required: true,
		displayOptions: { show: { resource: ['profiles'], operation: ['inject'] } },
		default: 1,
		description: 'ID of the campaign to associate the injected profiles with',
	},
];

export async function executeProfiles(
	this: IExecuteFunctions,
	i: number,
): Promise<INodeExecutionData[]> {
	const operation = this.getNodeParameter('operation', i) as string;

	if (operation === 'getMany') {
		const state = this.getNodeParameter('state', i) as string;
		const campaignIdFilter = this.getNodeParameter('campaignIdFilter', i) as number;

		const qs: IDataObject = {};
		if (state) {
			qs.state = state;
		}
		if (campaignIdFilter) {
			qs.campaign_id = campaignIdFilter;
		}

		const response = await openOutreachRequest.call(this, 'GET', '/profiles/', undefined, qs);

		// The API returns either a paginated object { count, results: [...] }
		// or a plain array. Handle both shapes.
		let items: IDataObject[];
		if (Array.isArray(response)) {
			items = response as IDataObject[];
		} else {
			const paginated = response as IDataObject;
			items = (paginated.results as IDataObject[]) ?? [paginated];
		}

		return items.map((item) => ({ json: item }));
	}

	if (operation === 'get') {
		const publicId = this.getNodeParameter('publicId', i) as string;
		const result = await openOutreachRequest.call(this, 'GET', `/profiles/${publicId}/`);
		return [{ json: result as IDataObject }];
	}

	if (operation === 'inject') {
		const urls = this.getNodeParameter('urls', i) as string[];
		const campaignId = this.getNodeParameter('campaignId', i) as number;

		const body: IDataObject = {
			urls,
			campaign_id: campaignId,
		};

		const response = await openOutreachRequest.call(this, 'POST', '/profiles/', body);

		// The inject endpoint returns a 207 multi-status array
		let results: IDataObject[];
		if (Array.isArray(response)) {
			results = response as IDataObject[];
		} else {
			results = [response as IDataObject];
		}

		return results.map((item) => ({ json: item }));
	}

	throw new Error(`Unknown profiles operation: ${operation}`);
}
