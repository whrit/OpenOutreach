import {
	IDataObject,
	IExecuteFunctions,
	INodeExecutionData,
	INodeProperties,
	NodeOperationError,
} from 'n8n-workflow';
import { openOutreachRequest } from '../helpers';

export const campaignsOperations: INodeProperties[] = [
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		displayOptions: { show: { resource: ['campaigns'] } },
		options: [
			{ name: 'Get', value: 'get', description: 'Get a single campaign by ID', action: 'Get a campaign' },
			{ name: 'Get Many', value: 'getMany', description: 'List all campaigns', action: 'Get many campaigns' },
			{ name: 'Update', value: 'update', description: 'Update campaign fields', action: 'Update a campaign' },
		],
		default: 'getMany',
	},
];

export const campaignsFields: INodeProperties[] = [
	{
		displayName: 'Campaign ID',
		name: 'campaignId',
		type: 'number',
		required: true,
		displayOptions: { show: { resource: ['campaigns'], operation: ['get', 'update'] } },
		default: 0,
		description: 'Numeric ID of the campaign. Replace 0 with your actual campaign ID.',
	},
	{
		displayName: 'Return All',
		name: 'returnAll',
		type: 'boolean',
		displayOptions: { show: { resource: ['campaigns'], operation: ['getMany'] } },
		default: false,
		description: 'Whether to return all results or only up to a given limit',
	},
	{
		displayName: 'Limit',
		name: 'limit',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 1000 },
		displayOptions: { show: { resource: ['campaigns'], operation: ['getMany'], returnAll: [false] } },
		default: 50,
		description: 'Max number of results to return',
	},
	{
		displayName: 'Product Docs',
		name: 'productDocs',
		type: 'string',
		typeOptions: { rows: 4 },
		displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } },
		default: '',
		description: 'Product documentation used to qualify leads (leave blank to keep unchanged)',
	},
	{
		displayName: 'Campaign Objective',
		name: 'campaignObjective',
		type: 'string',
		typeOptions: { rows: 4 },
		displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } },
		default: '',
		description: 'Objective of this campaign (leave blank to keep unchanged)',
	},
	{
		displayName: 'Follow-up Template',
		name: 'followupTemplate',
		type: 'string',
		typeOptions: { rows: 6 },
		displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } },
		default: '',
		description: 'Jinja2 follow-up message template (leave blank to keep unchanged)',
	},
	{
		displayName: 'Booking Link',
		name: 'bookingLink',
		type: 'string',
		displayOptions: { show: { resource: ['campaigns'], operation: ['update'] } },
		default: '',
		description: 'Booking link appended to follow-up messages (leave blank to keep unchanged)',
	},
];

export async function executeCampaigns(
	this: IExecuteFunctions,
	i: number,
): Promise<INodeExecutionData[]> {
	const operation = this.getNodeParameter('operation', i) as string;

	if (operation === 'getMany') {
		const returnAll = this.getNodeParameter('returnAll', i, false) as boolean;
		const limit = this.getNodeParameter('limit', i, 50) as number;
		let items: IDataObject[] = [];

		if (returnAll) {
			let page = 1;
			while (true) {
				const response = (await openOutreachRequest.call(
					this, 'GET', '/campaigns/', undefined, { page },
				)) as IDataObject;
				const pageItems: IDataObject[] = Array.isArray(response.results)
					? (response.results as IDataObject[])
					: (Array.isArray(response) ? (response as unknown as IDataObject[]) : []);
				items.push(...pageItems);
				if (!response.next) break;
				page++;
			}
		} else {
			const response = await openOutreachRequest.call(
				this, 'GET', '/campaigns/', undefined, { page_size: limit },
			);
			if (Array.isArray(response)) {
				items = response as IDataObject[];
			} else {
				const paginated = response as IDataObject;
				items = (paginated.results as IDataObject[]) ?? [paginated];
			}
		}

		return items.map((r) => ({ json: r }));
	}

	const campaignId = this.getNodeParameter('campaignId', i) as number;

	if (operation === 'get') {
		const result = (await openOutreachRequest.call(
			this,
			'GET',
			`/campaigns/${campaignId}/`,
		)) as IDataObject;
		return [{ json: result }];
	}

	if (operation === 'update') {
		const body: IDataObject = {};
		const pd = this.getNodeParameter('productDocs', i, '') as string;
		const co = this.getNodeParameter('campaignObjective', i, '') as string;
		const ft = this.getNodeParameter('followupTemplate', i, '') as string;
		const bl = this.getNodeParameter('bookingLink', i, '') as string;
		if (pd) body.product_docs = pd;
		if (co) body.campaign_objective = co;
		if (ft) body.followup_template = ft;
		if (bl) body.booking_link = bl;
		if (Object.keys(body).length === 0) {
			throw new NodeOperationError(
				this.getNode(),
				'At least one field must be provided to update a campaign. All fields were left blank.',
			);
		}
		const result = (await openOutreachRequest.call(
			this,
			'PATCH',
			`/campaigns/${campaignId}/`,
			body,
		)) as IDataObject;
		return [{ json: result }];
	}

	throw new NodeOperationError(this.getNode(), `Unknown campaigns operation: ${operation}`);
}
