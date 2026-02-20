import {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeConnectionTypes,
	NodeOperationError,
} from 'n8n-workflow';

import { profilesOperations, profilesFields, executeProfiles } from './actions/profiles';
import { campaignsOperations, campaignsFields, executeCampaigns } from './actions/campaigns';
import { lanesOperations, lanesFields, executeLanes } from './actions/lanes';
import { jobsOperations, jobsFields, executeJobs } from './actions/jobs';

export class OpenOutreach implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'OpenOutreach',
		name: 'openOutreach',
		icon: 'file:openoutreach.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["resource"] + ": " + $parameter["operation"]}}',
		description: 'Interact with OpenOutreach LinkedIn automation',
		defaults: { name: 'OpenOutreach' },
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		usableAsTool: true,
		credentials: [{ name: 'openOutreachApi', required: true }],
		properties: [
			{
				displayName: 'Resource',
				name: 'resource',
				type: 'options',
				noDataExpression: true,
				options: [
					{ name: 'Campaign', value: 'campaigns' },
					{ name: 'Job', value: 'jobs' },
					{ name: 'Lane', value: 'lanes' },
					{ name: 'Profile', value: 'profiles' },
				],
				default: 'profiles',
			},
			...profilesOperations,
			...profilesFields,
			...campaignsOperations,
			...campaignsFields,
			...lanesOperations,
			...lanesFields,
			...jobsOperations,
			...jobsFields,
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const resource = this.getNodeParameter('resource', 0) as string;
		const results: INodeExecutionData[] = [];

		for (let i = 0; i < items.length; i++) {
			if (resource === 'profiles') {
				results.push(...(await executeProfiles.call(this, i)));
			} else if (resource === 'campaigns') {
				results.push(...(await executeCampaigns.call(this, i)));
			} else if (resource === 'lanes') {
				results.push(...(await executeLanes.call(this, i)));
			} else if (resource === 'jobs') {
				results.push(...(await executeJobs.call(this, i)));
			} else {
				throw new NodeOperationError(this.getNode(), `Unknown resource: ${resource}`);
			}
		}

		return [results];
	}
}
